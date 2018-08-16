import base64
import os
import tempfile
import math

import bpy
from bpy_extras.image_utils import load_image
from mathutils import Vector


def create_image(op, idx):
    image = op.gltf['images'][idx]

    img = None
    if 'uri' in image:
        uri = image['uri']
        is_data_uri = uri[:5] == 'data:'
        if is_data_uri:
            found_at = uri.find(';base64,')
            if found_at == -1:
                print('error loading image: data URI not base64?')
                return None
            else:
                buffer = base64.b64decode(uri[found_at + 8:])
        else:
            # Load the image from disk
            image_location = os.path.join(op.base_path, uri)
            img = load_image(image_location)
    else:
        buffer, _stride = op.get('buffer_view', image['bufferView'])

    if not img:
        # The image data is in buffer, but I don't know how to load an image
        # from memory. We'll write it to a temp file and load it from there.
        # Yes, this is a hack :)
        with tempfile.TemporaryDirectory() as tmpdir:
            # TODO: use the image's name, if it has one, for the file path; but
            # we'll need to sanitize it in case it contains bad characters for a
            # file name somehow
            img_path = os.path.join(tmpdir, 'image_%d' % idx)
            with open(img_path, 'wb') as f:
                f.write(buffer)
            img = load_image(img_path)
            img.pack()  # TODO: should we use as_png?

    return img


def create_material(op, idx):
    """Create a Blender material for the glTF materials[idx]. If idx is the
    special value 'default_material', create a Blender material for the default
    glTF material instead.
    """
    use_color0 = idx in op.materials_using_color0

    if idx == 'default_material':
        return create_material_from_properties(op, {}, 'gltf Default Material', use_color0)

    material = op.gltf['materials'][idx]
    material_name = material.get('name', 'materials[%d]' % idx)
    return create_material_from_properties(op, material, material_name, use_color0)


def create_material_from_properties(op, material, material_name, use_color0):
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    tree = mat.node_tree
    links = tree.links

    while tree.nodes:
        tree.nodes.remove(tree.nodes[0])

    g = tree.nodes.new('ShaderNodeGroup')
    g.location = 43, 68
    g.width = 255
    if 'KHR_materials_unlit' in material.get('extensions', {}):
        pbr = material.get('pbrMetallicRoughness', {})
        g.node_tree = op.get('node_group', 'glTF Unlit')
    elif 'KHR_materials_pbrSpecularGlossiness' in material.get('extensions', {}):
        pbr = material['extensions']['KHR_materials_pbrSpecularGlossiness']
        g.node_tree = op.get('node_group', 'glTF Specular Glossiness')
    else:
        pbr = material.get('pbrMetallicRoughness', {})
        g.node_tree = op.get('node_group', 'glTF Metallic Roughness')

    mo = tree.nodes.new('ShaderNodeOutputMaterial')
    mo.location = 365, -25
    links.new(g.outputs[0], mo.inputs[0])


    # Alpha mode affects many things. Do it first.
    alpha_mode = material.get('alphaMode', 'OPAQUE')
    # mog_alpha modifies RGBA alpha values based on the alpha mode
    if alpha_mode == 'OPAQUE':
        def mog_alpha(rgba): return rgba[:3] + [1]
    elif alpha_mode == 'BLEND' or alpha_mode == 'MASK':
        def mog_alpha(rgba): return rgba
    else:
        print('unsupported alpha mode: %s' % alpha_mode)
        def mog_alpha(rgba): return rgba

    if alpha_mode == 'MASK':
        g.inputs['AlphaMode'].default_value = 1.0

    # This is only used in the Material view
    game_alpha_mode = {
        'OPAQUE': 'OPAQUE',
        'MASK': 'CLIP',
        'BLEND': 'ALPHA',
    }.get(alpha_mode, 'OPAQUE')
    if not material.get('doubleSided', False) and game_alpha_mode == 'OPAQUE':
        # Culling is emulated by making backfacing faces transparent, so we need
        # to enable alpha to get that to work
        game_alpha_mode = 'CLIP'
    mat.game_settings.alpha_blend = game_alpha_mode


    # Now wire up constant (ie. non-texture) material properties
    def set_value(obj, key, input_name, mog=lambda x: x):
        if key in obj and input_name in g.inputs:
            g.inputs[input_name].default_value = mog(obj[key])

    def rgb2rgba(rgb): return rgb + [1]

    set_value(pbr, 'baseColorFactor', 'BaseColorFactor', mog=mog_alpha)
    set_value(pbr, 'diffuseFactor', 'DiffuseFactor', mog=mog_alpha)
    set_value(pbr, 'metallicFactor', 'MetallicFactor')
    set_value(pbr, 'roughnessFactor', 'RoughnessFactor')
    set_value(pbr, 'specularFactor', 'SpecularFactor', mog=rgb2rgba)
    set_value(pbr, 'glossinessFactor', 'GlossinessFactor')
    set_value(material, 'emissiveFactor', 'EmissiveFactor', mog=rgb2rgba)
    set_value(material, 'alphaCutoff', 'AlphaCutoff')
    set_value(material, 'doubleSided', 'DoubleSided', mog=int)


    # Now textures. First, make a list of all the textures we'll need. The list
    # contains pairs (glTF textureInfo, g's input node name).
    textures = [
        (obj[prop_name], input_name)
        for obj, prop_name, input_name in [
            (pbr, 'baseColorTexture', 'BaseColor'),
            (pbr, 'diffuseTexture', 'Diffuse'),
            (pbr, 'metallicRoughnessTexture', 'MetallicRoughness'),
            (pbr, 'specularGlossinessTexture', 'Specular'),
            (material, 'normalTexture', 'Normal'),
            (material, 'occlusionTexture', 'Occlusion'),
            (material, 'emissiveTexture', 'Emissive'),
        ]
        if prop_name in obj and input_name in g.inputs
    ]

    # We'll line the texture nodes up in a vertical column centered on g
    x = g.location[0] - 480
    y = g.location[1] + (len(textures) * 300 + (len(textures) - 1) * 10) / 2 - 300
    y_step = -310

    for texinfo, input in textures:
        tex = create_texture_node(op, tree, texinfo, x, y)
        y += y_step
        tex.name = {
            'BaseColor': 'Base Color Texture',
            'Diffuse': 'Diffuse Texture',
            'MetallicRoughness': 'Metallic-Roughness Texture',
            'Specular': 'Specular-Glossiness Texture',
            'Normal': 'Normal Texture',
            'Occlusion': 'Occlusion Texture',
            'Emissive': 'Emissive Texture',
        }[input]
        tex.label = tex.name
        links.new(tex.outputs[0], g.inputs[input])

        # Special handling for particular types
        if input == 'BaseColor' or input == 'Diffuse':
            tex.color_space = 'COLOR'
            if alpha_mode != 'OPAQUE':
                links.new(tex.outputs[1], g.inputs['Alpha'])
        elif input == 'Specular':
            tex.color_space = 'COLOR'
            links.new(tex.outputs[1], g.inputs['Glossiness'])
        elif input == 'Normal':
            if 'scale' in material['normalTexture']:
                g.inputs['NormalScale'].default_value = material['normalTexture']['scale']
        elif input == 'Occlusion':
            if 'strength' in material['occlusionTexture']:
                g.inputs['OcclusionStrength'].default_value = material['occlusionTexture']['strength']
        elif input == 'Emissive':
            tex.color_space = 'COLOR'


    if use_color0:
        node = tree.nodes.new('ShaderNodeAttribute')
        node.name = 'Vertex Colors'
        node.location = [g.location[0] - 310, y]
        node.attribute_name = 'COLOR_0'
        links.new(node.outputs[0], g.inputs['COLOR_0'])
        g.inputs['Use COLOR_0'].default_value = 1.0


    return mat


# This function creates an Image Texture node for each texture, plus any
# nodes needed for its wrapping mode, texture transform, etc.
def create_texture_node(op, tree, info, x, y):
    links = tree.links
    texture = op.gltf['textures'][info['index']]

    img_texture = tree.nodes.new('ShaderNodeTexImage')
    if 'MSFT_texture_dds' in info.get('extensions', {}):
        image_id = texture['MSFT_texture_dds']['source']
    else:
        image_id = texture['source']
    img_texture.image = op.get('image', image_id)
    img_texture.width = 216
    img_texture.location = [x, y]

    # Now we need to make some nodes to handle the texture coordinates that get
    # fed into the texture node. There are three possible stages (they can be
    # absent)
    #
    #     [texcoord] -> [KHR texture transform] -> [wrapping calc]
    #
    # * The texcoord picks out which of the TEXCOORD_X attributes we use. It
    #   always has to be present if the others are or if X is not 0.
    # * The texture transform implements the KHR_texture_transform extension.
    # * The wrapping calc is for the wrapping mode, because though you can set
    #   the wrapping mode on the image texture node, it is too limited to cover
    #   all the possibilities.

    # Record all the nodes we put in each stage. We need this later to position
    # them nicely. During the first pass, we put the nodes where they would go
    # if they were the only stage, ie. just to the left of the Image Texture
    # node.
    texcoord_nodes = []
    texture_transform_nodes = []
    wrapping_nodes = []
    # The output socket of the last stage
    # HACK: inside of an array because Python reasons
    last_output = [None]


    texcoord_set = info.get('texCoord', 0)

    # Get the output from the last stage to link in. If there is no last stage,
    # lazily creates the [texcoord] stage and uses its output.
    def get_incoming():
        if last_output[0] is None:
            texcoord_node = tree.nodes.new('ShaderNodeUVMap') # TODO: is this the right kind of node?
            texcoord_node.location = [x - 260, y]
            texcoord_node.uv_map = 'TEXCOORD_%d' % texcoord_set
            texcoord_nodes.append(texcoord_node)
            last_output[0] = texcoord_node.outputs[0]
        return last_output[0]


    # Handle any texture transform
    # TODO: test this!!!
    if 'KHR_texture_transform' in texture.get('extensions', {}):
        t = texture['extensions']['KHR_texture_transform']

        texcoord_set = t.get('texCoord', texcoord_set)
        offset = t.get('offset', [0, 0])
        rotation = t.get('rotation', 0)
        scale = t.get('scale', [1, 1])

        # We need a coordinate change since we change (u,v)->(u,1-v) when we
        # come into Blender. My calculation gave this but again it is NOT
        # TESTED! It does fix the identity though, so that's promising :)
        z = scale[1] * Vector((-math.sin(rotation), -math.cos(rotation)))
        offset, rotation, scale = (
            z + Vector((offset[0], 1 - offset[1])),
            -rotation,
            [scale[0], scale[1]],
        )

        xform = tree.nodes.new('ShaderNodeMapping')
        xform.location = [x - 400, y]
        texture_transform_nodes.append(xform)

        xform.vector_type = 'VECTOR' # TODO: or 'TEXTURE'?
        xform.translation[0] = offset[0]
        xform.translation[1] = offset[1]
        xform.rotation[2] = rotation
        xform.scale[0] = scale[0]
        xform.scale[1] = scale[1]

        links.new(get_incoming(), xform.inputs[0])
        last_output[0] = xform.outputs[0]


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
    # Ignore mipmaps.
    min_filter = (
        NEAREST
        if min_filter in [NEAREST_MIPMAP_NEAREST, NEAREST_MIPMAP_LINEAR]
        else LINEAR
    )
    # We can't set the min and mag and filters separately in Blender. Just
    # prefer linear, unless both were nearest.
    if (min_filter, mag_filter) == (NEAREST, NEAREST):
        img_texture.interpolation = 'Closest'
    else:
        img_texture.interpolation = 'Linear'

    # Handle the wrapping mode.
    CLAMP_TO_EDGE = 33071
    MIRRORED_REPEAT = 33648
    REPEAT = 10497
    wrap_s = sampler.get('wrapS', REPEAT)
    wrap_t = sampler.get('wrapT', REPEAT)
    if (wrap_s, wrap_t) == (CLAMP_TO_EDGE, CLAMP_TO_EDGE):
        img_texture.extension = 'EXTEND'
    elif (wrap_s, wrap_t) == (REPEAT, REPEAT):
        img_texture.extension = 'REPEAT'
    else:
        # Damn, Blender can't do this. We have to insert the wrapping stage :(
        img_texture.extension = 'EXTEND'
        frame = tree.nodes.new('NodeFrame')
        frame.label = 'Wrapping Mode'
        wrapping_nodes.append(frame)
        frame.width, frame.height = 650, 244
        frame.location = [x - 963, y - 90]

        sep_xyz = tree.nodes.new('ShaderNodeSeparateXYZ')
        com_xyz = tree.nodes.new('ShaderNodeCombineXYZ')
        sep_xyz.parent = frame
        com_xyz.parent = frame
        sep_xyz.location = [212, 12]
        com_xyz.location = [727, 45]
        links.new(get_incoming(), sep_xyz.inputs[0])

        def do_component(wrap, which, y):
            if wrap not in [CLAMP_TO_EDGE, MIRRORED_REPEAT, REPEAT]:
                print('unknown wrap mode: %s' % wrap)
                wrap = REPEAT

            if wrap == CLAMP_TO_EDGE:
                links.new(sep_xyz.outputs[which], com_xyz.inputs[which])
            else:
                n = tree.nodes.new('ShaderNodeGroup')
                n.parent = frame
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

        do_component(wrap_s, 'X', y=90)
        do_component(wrap_t, 'Y', y=-50)

        last_output[0] = com_xyz.outputs[0]


    # Wire the last stage into the Image Texture Node
    # Always make a texcoord node for TEXCOORD_X, X != 0
    if texcoord_set != 0:
        get_incoming()
    if last_output[0]:
        links.new(last_output[0], img_texture.inputs[0])


    # As promised, we now place the nodes in nice positions by moving each stage
    # to the left to make room for the stages that come after it.
    def move_back(nodes, delta):
        for node in nodes: node.location[0] -= delta
    if wrapping_nodes:
        move_back(texture_transform_nodes, 780)
        move_back(texcoord_nodes, 780)
    if texture_transform_nodes:
        move_back(texcoord_nodes, 400)


    return img_texture




def compute_materials_using_color0(op):
    """Compute which materials use vertex color COLOR_0.

    I don't know how to have a material be influenced by vertex colors when a
    mesh has them and not be when they aren't. If you slot in an attribute node
    it will emit solid red when the attribute layer is missing (if it produced
    solid white everything would be fine) and, of course, if you don't the
    attribute won't influence the material.

    Hence this work-around: we compute for each material whether it is ever used
    in a primitive that uses vertex colors and mark it down. For these materials
    only we slot in an attribute node for vertex colors. In mesh.py we also need
    to make sure that any mesh that uses one of these materials has a COLOR_0
    attribute.
    """
    op.materials_using_color0 = set()
    for mesh in op.gltf.get('meshes', []):
        for primitive in mesh['primitives']:
            if 'COLOR_0' in primitive['attributes']:
                mat = primitive.get('material', 'default_material')
                op.materials_using_color0.add(mat)
