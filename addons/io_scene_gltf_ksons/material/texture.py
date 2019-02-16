import json
from . import block
Block = block.Block

# Creates a texture block for the given material.
#
# The texture block reads the appropriate texcoord set, possibly transforms
# the UVs for KHR_texture_transform, applies wrapping to the UVs, and
# samples an image texture. In general, it looks like
#
#    [Texcoord] -> [UV Transform] -> [UV Wrap] -> [Img Texture] ->


def create_texture_block(mc, texture_type, info):
    texture = mc.op.gltf['textures'][info['index']]

    texcoord_set = info.get('texCoord', 0)
    block = None
    # We'll create the texcoord block lazily
    def create_texcoord_block():
        return mc.adjoin({
            'node': 'UVMap',
            'prop.uv_map': 'TEXCOORD_%d' % texcoord_set,
        })

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
        (texture_type + '-transform') in mc.op.material_infos[mc.idx].liveness
    )
    if needs_tex_transform:
        t = info.get('extensions', {}).get('KHR_texture_transform', {})

        texcoord_set = t.get('texCoord', texcoord_set)
        offset = t.get('offset', [0, 0])
        rotation = t.get('rotation', 0)
        scale = t.get('scale', [1, 1])

        # Rotation is counter-clockwise, but in glTF's UV space where Y is down,
        # which makes it a clockwise rotation in normal terms
        rotation = -rotation

        # [Texcoord] -> [gltf<->Blender]
        if not block:
            block = create_texcoord_block()
        block = mc.adjoin({
            'node': 'Group',
            'group': 'glTF <-> Blender UV',
            'input.0': block,
        })

        # -> [Transform]
        block = mc.adjoin({
            'node': 'Mapping',
            'dim': (320, 275),
            'prop.vector_type': 'POINT',
            'input.0': block,
        })
        mapping_node = block.outputs[0].node
        mapping_node.translation[0], mapping_node.translation[1] = offset
        mapping_node.rotation[2] = rotation
        mapping_node.scale[0], mapping_node.scale[1] = scale

        mc.op.material_infos[mc.idx].paths[texture_type + '-transform'] = (
            'nodes[' + json.dumps(mapping_node.name) + ']'
        )

        # -> [gltf<->Blender]
        block = mc.adjoin({
            'node': 'Group',
            'group': 'glTF <-> Blender UV',
            'input.0': block,
        })

    if 'sampler' in texture:
        sampler = mc.op.gltf['samplers'][texture['sampler']]
    else:
        sampler = {}

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
        extension = 'EXTEND'
    elif (wrap_s, wrap_t) == (REPEAT, REPEAT):
        extension = 'REPEAT'
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
        extension = 'EXTEND'

        if not block:
            block = create_texcoord_block()

        # -> [separate XYZ]
        block = mc.adjoin({
            'node': 'SeparateXYZ',
            'input.0': block,
        })

        # -> [wrap S]
        # -> [wrap T]
        gltf_to_blender_wrap = dict([
            (REPEAT, 'Texcoord REPEAT'),
            (MIRRORED_REPEAT, 'Texcoord MIRRORED_REPEAT'),
        ])
        block = mc.adjoin_split(
            {
                'node': 'Group',
                'dim': (230, 100),
                'group': gltf_to_blender_wrap[wrap_s],
                'input.0': block,
            } if wrap_s != CLAMP_TO_EDGE else {},
            {
                'node': 'Group',
                'dim': (230, 100),
                'group': gltf_to_blender_wrap[wrap_t],
                'output.1/input.0': block,
            } if wrap_t != CLAMP_TO_EDGE else {},
            block,
        )

        # -> [combine XYZ]
        block = mc.adjoin({
            'node': 'CombineXYZ',
            'output.0/input.0': block,
            'output.1/input.1': block,
        })

    # Determine interpolation.

    NEAREST = 9728
    LINEAR = 9729
    NEAREST_MIPMAP_NEAREST = 9984
    LINEAR_MIPMAP_NEAREST = 9985
    NEAREST_MIPMAP_LINEAR = 9986
    LINEAR_MIPMAP_LINEAR = 9987
    AUTO_FILTER = LINEAR  # which one to use if unspecified

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
        print('unknown texture min filter:', min_filter)
        min_filter = AUTO_FILTER

    # We can't set the min and mag and filters separately in Blender. Just
    # prefer linear, unless both were nearest.
    if (min_filter, mag_filter) == (NEAREST, NEAREST):
        interpolation = 'Closest'
    else:
        interpolation = 'Linear'

    # Find source
    if 'MSFT_texture_dds' in info.get('extensions', {}):
        image_id = texture['MSFT_texture_dds']['source']
        image = mc.op.get('image', image_id)
    elif 'source' not in texture:
        image = None
    else:
        image_id = texture['source']
        image = mc.op.get('image', image_id)

    # -> [TexImage]
    if not block and texcoord_set != 0:
        block = create_texcoord_block()
    block = mc.adjoin({
        'node': 'TexImage',
        'dim': (220, 250),
        'prop.image': image,
        'prop.interpolation': interpolation,
        'prop.extension': extension,
        'input.0': block,
    })

    block.img_node = block.outputs[0].node

    return block
