import json
import bpy
from . import block
from .texture import create_texture_block
Block = block.Block

class Value:
    def __init__(self, value, record_to=''):
        self.value = value
        self.record_to = record_to


class MaterialCreator:
    def adjoin(self, opts):
        new_node = self.tree.nodes.new('ShaderNode' + opts['node'])
        new_node.width = 140
        new_node.height = 100

        def str_or_int(x):
            try:
                return int(x)
            except ValueError:
                return x

        input_blocks = []
        for key, val in opts.items():
            if key.startswith('input.'):
                input_key = str_or_int(key[len('input.'):])
                input_block = self.connect(val, 0, new_node, 'inputs', input_key)
                if input_block and input_block not in input_blocks:
                    input_blocks.append(input_block)

            elif key.startswith('output.'):
                if '/' in key:
                    output_part, input_part = key.split('/')
                    output_key = str_or_int(output_part[len('output.'):])
                    input_key = str_or_int(input_part[len('input.'):])
                    input_block = self.connect(val, output_key, new_node, 'inputs', input_key)
                    if input_block and input_block not in input_blocks:
                        input_blocks.append(input_block)

                else:
                    output_key = str_or_int(key[len('output.'):])
                    input_block = self.connect(val, 0, new_node, 'outputs', output_key)
                    if input_block and input_block not in input_blocks:
                        input_blocks.append(input_block)

            elif key.startswith('prop.'):
                prop_name = key[len('prop.'):]
                setattr(new_node, prop_name, val)

            elif key == 'dim':
                new_node.width, new_node.height = val

        input_block = Block.col_align_right(input_blocks)

        block = Block.row_align_center([input_block, new_node])
        block.outputs = new_node.outputs

        return block

    def connect(self, connector, connector_key, node, socket_type, socket_key):
        if type(connector) == Value:
            connector = [connector]

        if type(connector) == list:
            self.connect_value(connector[connector_key], node, socket_type, socket_key)
            return None

        else:
            assert(socket_type == 'inputs')
            self.connect_block(connector, connector_key, node.inputs[socket_key])
            return connector

    def connect_value(self, value, node, socket_type, socket_key):
        getattr(node, socket_type)[socket_key].default_value = value.value
        if value.record_to:
            self.op.material_infos[self.idx].paths[value.record_to] = (
                'nodes[' + json.dumps(node.name) + ']' +
                '.' + socket_type + '[' + json.dumps(socket_key) + ']'
            )

    def connect_block(self, block, output_key, socket):
        self.links.new(block.outputs[output_key], socket)


def create_material(op, idx):
    """
    Create a Blender material for the glTF materials[idx]. If idx is the
    special value 'default_material', create a Blender material for the default
    glTF material instead.
    """
    mc = MaterialCreator()
    mc.op = op
    mc.idx = idx

    if idx == 'default_material':
        mc.material = {}
        material_name = 'glTF Default Material'
    else:
        mc.material = op.gltf['materials'][idx]
        material_name = mc.material.get('name', 'materials[%d]' % idx)

    if 'KHR_materials_unlit' in mc.material.get('extensions', {}):
        mc.pbr = mc.material.get('pbrMetallicRoughness', {})
        mc.type = 'unlit'
    elif 'KHR_materials_pbrSpecularGlossiness' in mc.material.get('extensions', {}):
        mc.pbr = mc.material['extensions']['KHR_materials_pbrSpecularGlossiness']
        mc.type = 'specGloss'
    else:
        mc.pbr = mc.material.get('pbrMetallicRoughness', {})
        mc.type = 'metalRough'

    # Create a new Blender node-tree material and empty it
    bl_material = bpy.data.materials.new(material_name)
    bl_material.use_nodes = True
    mc.tree = bl_material.node_tree
    mc.links = mc.tree.links
    while mc.tree.nodes:
        mc.tree.nodes.remove(mc.tree.nodes[0])

    create_node_tree(mc)

    # Set the viewport alpha mode
    alpha_mode = mc.material.get('alphaMode', 'OPAQUE')
    blend_method = {
        # Blender: glTF
        'OPAQUE': 'OPAQUE',
        'MASK': 'CLIP',
        'BLEND': 'ALPHA',
     }.get(alpha_mode, 'OPAQUE')
    if getattr(bl_material, 'blend_method', None):
        bl_material.blend_method = blend_method
    else:
        bl_material.game_settings.alpha_blend = blend_method

    # Set diffuse/specular color (for solid view)
    if 'baseColorFactor' in mc.pbr:
        bl_material.diffuse_color = mc.pbr['baseColorFactor'][:3]
    if 'diffuseFactor' in mc.pbr:
        bl_material.diffuse_color = mc.pbr['diffuseFactor'][:3]
    if 'specularFactor' in mc.pbr:
        bl_material.specular_color = mc.pbr['specularFactor']

    return bl_material


def create_node_tree(mc):
    emissive_block = None
    if mc.type != 'unlit':
        emissive_block = create_emissive(mc)
    shaded_block = create_shaded(mc)

    if emissive_block:
        block = mc.adjoin({
            'node': 'AddShader',
            'input.0': emissive_block,
            'input.1': shaded_block,
        })
    else:
        block = shaded_block

    alpha_block = create_alpha_block(mc)
    if alpha_block:
        block = mc.adjoin({
            'node': 'MixShader',
            'input.1': block,
            'output.0/input.Fac': alpha_block,
            'output.1/input.2': alpha_block,
        })

    mc.adjoin({
        'node': 'OutputMaterial',
        'input.Surface': block,
    })


def create_emissive(mc):
    if mc.type == 'unlit':
        return None

    block = None
    if 'emissiveTexture' in mc.material:
        block = create_texture_block(
            mc.op,
            mc.idx,
            'emissiveTexture',
            mc.tree,
            mc.material['emissiveTexture']
        )

    factor = mc.material.get('emissiveFactor', [0, 0, 0])

    if factor != [1, 1, 1]:
        if block:
            block = mc.adjoin({
                'node': 'MixRGB',
                'prop.blend_type': 'MULTIPLY',
                'input.Fac': Value(1),
                'input.Color1': block,
                'input.Color2': Value(factor + [1], record_to='emissiveFactor'),
            })
        else:
            if factor == [0, 0, 0]:
                block = None
            else:
                block = Value(factor + [1], record_to='emissiveFactor')

    if block:
        block = mc.adjoin({
            'node': 'Emission',
            'input.Color': block,
        })

    return block


def create_alpha_block(mc):
    alpha_mode = mc.material.get('alphaMode', 'OPAQUE')

    if alpha_mode == 'OPAQUE':
        return None

    if alpha_mode not in ['MASK', 'BLEND']:
        print('unknown alpha mode %s' % alpha_mode)
        return None

    block = mc.adjoin({
        'node': 'Math',
        'prop.operation': 'SUBTRACT',
        'input.0': Value(1),
    })
    # Link the image texture's alpha into invert block's second input slot
    # TODO: shouldn't we use the base color alpha instead?
    if getattr(mc, 'img_node', None):
        mc.links.new(
            mc.img_node.outputs[1],
            block.outputs[0].node.inputs[1]
        )

    if alpha_mode == 'MASK':
        alpha_cutoff = mc.material.get('alphaCutoff', 0.5)
        block = mc.adjoin({
            'node': 'Math',
            'prop.operation': 'GREATER_THAN',
            'input.0': block,
            'input.1': Value(alpha_cutoff, record_to='alphaCutoff'),
        })

    transparent_block = mc.adjoin({
        'node': 'BsdfTransparent',
    })

    alpha_block = Block.col_align_right([block, transparent_block])
    alpha_block.outputs = [block.outputs[0], transparent_block.outputs[0]]

    return alpha_block


def create_shaded(mc):
    if mc.type == 'metalRough':
        return create_metalRough_pbr(mc)
    elif mc.type == 'specGloss':
        return create_specGloss_pbr(mc)
    elif mc.type == 'unlit':
        return create_unlit(mc)
    else:
        assert(False)


def create_metalRough_pbr(mc):
    params = {
        'node': 'BsdfPrincipled',
        'dim': (200, 540),
    }

    base_color_block = create_base_color(mc)
    if base_color_block:
        params['input.Base Color'] = base_color_block

    metal_roughness_block = create_metal_roughness(mc)
    if metal_roughness_block:
        params['output.0/input.Metallic'] = metal_roughness_block
        params['output.1/input.Roughness'] = metal_roughness_block

    normal_block = create_normal_block(mc)
    if normal_block:
        params['input.Normal'] = normal_block

    return mc.adjoin(params)


def create_unlit(mc):
    params = {
        # TODO: pick a better node?
        'node': 'Emission',
    }

    base_color_block = create_base_color(mc)
    if base_color_block:
        params['input.Color'] = base_color_block

    return mc.adjoin(params)


def create_base_color(mc):
    block = None
    if 'baseColorTexture' in mc.pbr:
        block = create_texture_block(
            mc.op,
            mc.idx,
            'baseColorTexture',
            mc.tree,
            mc.pbr['baseColorTexture'],
        )
        # Remember for alpha value
        mc.img_node = block.img_node

    for color_set_num in range(0, mc.op.material_infos[mc.idx].num_color_sets):
        vert_color_block = mc.adjoin({
            'node': 'Attribute',
            'prop.attribute_name': 'COLOR_%d' % color_set_num,
        })
        if block:
            block = mc.adjoin({
                'node': 'MixRGB',
                'prop.blend_type': 'MULTIPLY',
                'input.Fac': Value(1),
                'input.Color1': block,
                'input.Color2': vert_color_block,
            })
        else:
            block = vert_color_block

    factor = mc.pbr.get('baseColorFactor', [1, 1, 1, 1])
    if factor != [1, 1, 1, 1]:
        if block:
            block = mc.adjoin({
                'node': 'MixRGB',
                'prop.blend_type': 'MULTIPLY',
                'input.Fac': Value(1),
                'input.Color1': block,
                'input.Color2': Value(factor, record_to='baseColorFactor'),
            })
        else:
            block = Value(factor, record_to='baseColorFactor')

    return block


def create_metal_roughness(mc):
    block = None
    if 'metallicRoughnessTexture' in mc.pbr:
        tex_block = create_texture_block(
            mc.op,
            mc.idx,
            'metallicRoughnessTexture',
            mc.tree,
            mc.pbr['metallicRoughnessTexture'],
        )
        tex_block.img_node.color_space = 'NONE'

        block = mc.adjoin({
            'node': 'SeparateRGB',
            'input.Image': tex_block,
        })
        block.outputs = [block.outputs['B'], block.outputs['G']]

    metal_factor = mc.pbr.get('metallicFactor', 1)
    rough_factor = mc.pbr.get('roughFactor', 1)

    if metal_factor == 1 and rough_factor == 1:
        return block

    if not block:
        return [
            Value(metal_factor, record_to='metallicFactor'),
            Value(rough_factor, record_to='roughFactor'),
        ]

    metal_factor_block = None
    if metal_factor != 1:
        metal_factor_block = mc.adjoin({
            'node': 'Math',
            'prop.operation': 'MULTIPLY',
            'input.0': Value(metal_factor, record_to='metallicFactor'),
        })
        mc.links.new(
            block.outputs[0],
            metal_factor_block.outputs[0].node.inputs[1],
        )

    rough_factor_block = None
    if rough_factor != 1:
        rough_factor_block = mc.adjoin({
            'node': 'Math',
            'prop.operation': 'MULTIPLY',
            'input.0': Value(rough_factor, record_to='roughnessFactor'),
        })
        mc.links.new(
            block.outputs[1],
            rough_factor_block.outputs[0].node.inputs[1],
        )

    factor_blocks = []
    if metal_factor_block:
        factor_blocks.append(metal_factor_block)
    if rough_factor_block:
        factor_blocks.append(rough_factor_block)
    factor_block = Block.col_align_right(factor_blocks)
    final_block = Block.row_align_center([block, factor_block])
    final_block.outputs = [block.outputs[0], block.outputs[1]]
    if metal_factor_block:
        final_block.outputs[0] = metal_factor_block.outputs[0]
    if rough_factor_block:
        final_block.outputs[1] = rough_factor_block.outputs[0]
    return final_block


def create_normal_block(mc):
    if 'normalTexture' in mc.material:
        tex_block = create_texture_block(
            mc.op,
            mc.idx,
            'normalTexture',
            mc.tree,
            mc.material['normalTexture'],
        )
        tex_block.img_node.color_space = 'NONE'

        return mc.adjoin({
            'node': 'NormalMap',
            'prop.uv_map': 'TEXCOORD_%d' % mc.material['normalTexture'].get('texCoord', 0),
            'input.Strength': Value(mc.material['normalTexture'].get('scale', 1), record_to='normalScale'),
            'input.Color': tex_block,
        })
    else:
        return None
