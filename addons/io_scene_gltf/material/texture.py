from . import block
Block = block.Block

# Creates a texture block for the given material.
#
# The texture block reads the appropriate texcoord set, possibly transforms
# the UVs for KHR_texture_transform, applies wrapping to the UVs, and
# samples an image texture. It looks like
#
#    [Texcoord] -> [UV Transform] -> [UV Wrap] -> [Img Texture] ->
#
# where some of these sub-blocks may be missing.
def create_texture_block(op, material_id, texture_type, tree, info):
    links = tree.links
    texture = op.gltf['textures'][info['index']]

    # First create the [Img Texture] block
    img_texture = tree.nodes.new('ShaderNodeTexImage')
    if 'MSFT_texture_dds' in info.get('extensions', {}):
        image_id = texture['MSFT_texture_dds']['source']
    elif 'source' not in texture:
        return None
    else:
        image_id = texture['source']
    img_texture.width, img_texture.height = 216, 247.25
    img_texture.image = op.get('image', image_id)
    subblocks = [img_texture]

    texcoord_set = info.get('texCoord', 0)

    # The [UV Transform] block looks like
    #
    #    -> [gltf<->Blender] -> [Transform] -> [gltf<->Blender] ->
    #
    # the [gltf<->Blender] blocks are Group Nodes that convert between glTF and
    # Blender UV conventions, ie. (u, v) -> (u, 1-v). [Transform] is a Mapping
    # Node that applies the actual TRS transform.
    needs_tex_transform = (
        'KHR_texture_transform' in info.get('extensions', {}) or
        # This is set if the texture transform is animated
        op.material_texture_has_animated_transform.get((material_id, texture_type))
    )
    if needs_tex_transform:
        t = info.get('extensions', {}).get('KHR_texture_transform', {})

        texcoord_set = t.get('texCoord', texcoord_set)
        offset = t.get('offset', [0, 0])
        rotation = t.get('rotation', 0)
        scale = t.get('scale', [1, 1])

        # First [gltf<->Blender]
        conv_before = tree.nodes.new('ShaderNodeGroup')
        conv_before.location = [167, -206]
        conv_before.width = 180
        conv_before.node_tree = op.get('node_group', 'glTF <-> Blender UV')

        # [Transform]
        xform = tree.nodes.new('ShaderNodeMapping')
        xform.name = texture_type + '_xform'
        xform.location = [408, -108]
        xform.vector_type = 'POINT'
        xform.translation[0], xform.translation[1] = offset
        xform.rotation[2] = rotation
        xform.scale[0], xform.scale[1] = scale

        # Last [gltf<->Blender]
        conv_after = tree.nodes.new('ShaderNodeGroup')
        conv_after.location = [790, -200]
        conv_after.width = 180
        conv_after.node_tree = op.get('node_group', 'glTF <-> Blender UV')

        links.new(conv_before.outputs[0], xform.inputs[0])
        links.new(xform.outputs[0], conv_after.inputs[0])

        subblock = Block(conv_before, xform, conv_after)
        subblock.framify(tree, 'Texcoord Transform')
        subblock.inputs = [conv_before.inputs[0]]
        subblock.outputs = [conv_after.outputs[0]]
        subblocks = [subblock] + subblocks


    if 'sampler' in texture:
        sampler = op.gltf['samplers'][texture['sampler']]
    else:
        sampler = {}

    # Set the magnification filter.
    NEAREST = 9728
    LINEAR = 9729
    NEAREST_MIPMAP_NEAREST = 9984
    LINEAR_MIPMAP_NEAREST = 9985
    NEAREST_MIPMAP_LINEAR = 9986
    LINEAR_MIPMAP_LINEAR = 9986
    AUTO_FILTER = LINEAR # which one to use if unspecified

    mag_filter = sampler.get('magFilter', AUTO_FILTER)
    min_filter = sampler.get('minFilter', AUTO_FILTER)
    if mag_filter not in [NEAREST, LINEAR]:
        print('unknown texture mag filter:', mag_filter)
        mag_filter = AUTO_FILTER
    # Ignore mipmaps.
    if min_filter in [NEAREST, NEAREST_MIPMAP_NEAREST, NEAREST_MIPMAP_LINEAR]:
        min_filter = NEAREST
    elif min_filter in [LINEAR, LINEAR_MIPMAP_NEAREST, LINEAR_MIPMAP_LINEAR]:
        min_filter = LINEAR
    else:
        print('unknown texture min filter:', mag_filter)
        mag_filter = AUTO_FILTER

    # We can't set the min and mag and filters separately in Blender. Just
    # prefer linear, unless both were nearest.
    if (min_filter, mag_filter) == (NEAREST, NEAREST):
        img_texture.interpolation = 'Closest'
    else:
        img_texture.interpolation = 'Linear'

    # Handle the wrapping mode. The Image Texture Node can have a wrapping mode
    # but it doesn't cover all possibilities in glTF.
    CLAMP_TO_EDGE = 33071
    MIRRORED_REPEAT = 33648
    REPEAT = 10497

    wrap_s = sampler.get('wrapS', REPEAT)
    wrap_t = sampler.get('wrapT', REPEAT)
    if wrap_s not in [CLAMP_TO_EDGE, MIRRORED_REPEAT, REPEAT]:
        print('unknown wrapping mode:', wrap_s)
        wrap_s = REPEAT
    if wrap_t not in [CLAMP_TO_EDGE, MIRRORED_REPEAT, REPEAT]:
        print('unknown wrapping mode:', wrap_t)
        wrap_t = REPEAT

    if (wrap_s, wrap_t) == (CLAMP_TO_EDGE, CLAMP_TO_EDGE):
        img_texture.extension = 'EXTEND'
    elif (wrap_s, wrap_t) == (REPEAT, REPEAT):
        img_texture.extension = 'REPEAT'
    else:
        # Blender couldn't handle it. We have to insert the [UV Wrap] block. It
        # looks like
        #
        #                      -> [wrap S] ->
        #    -> [separate XYZ]                [combine XYZ] ->
        #                      -> [wrap T] ->
        #
        # where the [wrap _] blocks are Group Nodes that compute
        #
        #     x -> x mod 1               for REPEAT
        #
        #     x -> / y       if y <= 1   for MIRRORED_REPEAT
        #          \ 2 - y   if y > 1
        #            where y = x mod 2
        #
        # and where the [wrap _] block is omitted (ie. the value is passed
        # through) for CLAMP_TO_EDGE because we set the wrapping mode on the
        # Texture Node to do clamping (the artifacts produced when we use
        # clamping for the actual wrapping mode are slightly better than if we
        # used another mode).
        img_texture.extension = 'EXTEND'

        nodes = []

        # [separate XYZ]
        sep_xyz = tree.nodes.new('ShaderNodeSeparateXYZ')
        sep_xyz.location = [212, 12]
        nodes.append(sep_xyz)

        # [combine XYZ]
        com_xyz = tree.nodes.new('ShaderNodeCombineXYZ')
        com_xyz.location = [727, 45]
        nodes.append(com_xyz)

        def do_component(wrap, which, y):
            if wrap == CLAMP_TO_EDGE:
                links.new(sep_xyz.outputs[which], com_xyz.inputs[which])
            else:
                n = tree.nodes.new('ShaderNodeGroup')
                nodes.append(n)
                n.width = 222
                n.location = [430, y]
                group_name = (
                    'Texcoord REPEAT'
                    if wrap == REPEAT
                    else 'Texcoord MIRRORED_REPEAT'
                )
                n.node_tree = op.get('node_group', group_name)
                links.new(sep_xyz.outputs[which], n.inputs[0])
                links.new(n.outputs[0], com_xyz.inputs[which])

        # [wrap S]
        do_component(wrap_s, 'X', y=90)
        # [wrap T]
        do_component(wrap_t, 'Y', y=-50)

        subblock = Block(*nodes)
        subblock.framify(tree, 'Texcoord Wrap')
        subblock.inputs = [sep_xyz.inputs[0]]
        subblock.outputs = [com_xyz.outputs[0]]
        subblocks = [subblock] + subblocks


    # Now we handle the [Texcoord] block. If there is only an [Img Texture]
    # subblock and the texcoord set is 0 (the most common case), we can skip
    # this too, since the Texture Node will pick it up automatically.
    if len(subblocks) == 1 and texcoord_set == 0:
        pass
    else:
        texcoord_node = tree.nodes.new('ShaderNodeUVMap') # TODO: is this the right kind of node?
        texcoord_node.uv_map = 'TEXCOORD_%d' % texcoord_set
        subblocks = [texcoord_node] + subblocks

    # Wire the subblocks up
    for i in range(1, len(subblocks)):
        links.new(subblocks[i-1].outputs[0], subblocks[i].inputs[0])

    row = Block.row_align_center(subblocks, gutter=80)

    # Mark this so our caller can find it
    row.img_texture_node = img_texture

    return row
