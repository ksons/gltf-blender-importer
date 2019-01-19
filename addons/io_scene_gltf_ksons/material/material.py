import bpy
from . import block
from .texture import create_texture_block
Block = block.Block


def create_material(op, idx):
    """Create a Blender material for the glTF materials[idx]. If idx is the
    special value 'default_material', create a Blender material for the default
    glTF material instead.
    """
    if idx == 'default_material':
        material = {}
        material_name = 'glTF Default Material'
    else:
        material = op.gltf['materials'][idx]
        material_name = material.get('name', 'materials[%d]' % idx)

    # In general a material's node tree looks like
    #
    #         [texture] ->
    #         [texture] -> [main] -> [output]
    #               ... ->
    #    [vertex color] ->
    #
    # where we'll call the blocks on the left _input blocks_, and [main] is a
    # Group Node that implements the shading model, eg. pbrMetallicRoughness.

    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    tree = mat.node_tree
    links = tree.links
    while tree.nodes:
        tree.nodes.remove(tree.nodes[0])

    # Create the right-most [main] -> [output] block
    g = tree.nodes.new('ShaderNodeGroup')
    g.name = 'main'
    g.width, g.height = 255, 452.75
    g.location = 0, 0
    if 'KHR_materials_unlit' in material.get('extensions', {}):
        pbr = material.get('pbrMetallicRoughness', {})
        g.node_tree = op.get('node_group', 'glTF Unlit')
    elif 'KHR_materials_pbrSpecularGlossiness' in material.get('extensions', {}):
        pbr = material['extensions']['KHR_materials_pbrSpecularGlossiness']
        g.node_tree = op.get('node_group', 'glTF Specular Glossiness')
    else:
        pbr = material.get('pbrMetallicRoughness', {})
        g.node_tree = op.get('node_group', 'glTF Metallic Roughness')

    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.width, output.height = 140, 89.75
    output.location = 625, -50
    links.new(g.outputs[0], output.inputs[0])

    right_block = Block(g, output)

    # Fill in properties on [main].
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

    # Now input blocks. First, create blocks for all the textures that we need,
    # ie. that are both in the glTF file and are used by [main].
    input_blocks = []
    possible_textures = [
        # (object, property on object, name of the corresponding input on g)
        (pbr, 'baseColorTexture', 'BaseColor'),
        (pbr, 'diffuseTexture', 'Diffuse'),
        (pbr, 'metallicRoughnessTexture', 'MetallicRoughness'),
        (pbr, 'specularGlossinessTexture', 'Specular'),
        (material, 'normalTexture', 'Normal'),
        (material, 'occlusionTexture', 'Occlusion'),
        (material, 'emissiveTexture', 'Emissive'),
    ]
    for (obj, prop, input) in possible_textures:
        if prop not in obj or input not in g.inputs:
            continue

        info = obj[prop]
        tex_block = create_texture_block(op, idx, prop, tree, info)
        if not tex_block:
            continue
        input_blocks.append(tex_block)

        tex = tex_block.img_texture_node
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
        elif input == 'MetallicRoughness':
            tex.color_space = 'NONE'
        elif input == 'Specular':
            tex.color_space = 'COLOR'
            links.new(tex.outputs[1], g.inputs['Glossiness'])
        elif input == 'Normal':
            tex.color_space = 'NONE'
            if 'scale' in material['normalTexture']:
                g.inputs['NormalScale'].default_value = material['normalTexture']['scale']
        elif input == 'Occlusion':
            tex.color_space = 'NONE'
            if 'strength' in material['occlusionTexture']:
                g.inputs['OcclusionStrength'].default_value = material['occlusionTexture']['strength']
        elif input == 'Emissive':
            tex.color_space = 'COLOR'

    # Add a vertex color node if needed.
    use_color0 = idx in op.materials_using_color0
    if use_color0:
        node = tree.nodes.new('ShaderNodeAttribute')
        node.name = 'Vertex Colors'
        node.attribute_name = 'COLOR_0'
        links.new(node.outputs[0], g.inputs['COLOR_0'])
        g.inputs['Use COLOR_0'].default_value = 1.0

        input_blocks.append(node)

    # Lay the blocks out like this and then center the whole thing.
    #     .-------. .---.
    #     | Input | | M | .--------.
    #    .--------+ | a | | Output |
    #    |  Input | | i | '--------'
    #    '--------+ | n |
    #     | Input | |   |
    #     '-------' '---'
    left_block = Block.col_align_right(input_blocks, gutter=70)
    whole = Block.row_align_center([left_block, right_block], gutter=600)
    block.center_at_origin(whole)

    return mat
