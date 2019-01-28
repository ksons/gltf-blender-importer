import bpy
from . import block
from .texture import create_texture_block
Block = block.Block

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
                self.links.new(val.outputs[0], new_node.inputs[input_key])
                if val not in input_blocks:
                    input_blocks.append(val)

            elif key.startswith('output.'):
                output_part, input_part = key.split('/')
                output_key = str_or_int(output_part[len('output.'):])
                input_key = str_or_int(input_part[len('input.'):])
                self.links.new(val.outputs[output_key], new_node.inputs[input_key])
                if val not in input_blocks:
                    input_blocks.append(val)

            elif key.startswith('value.'):
                input_name = key[len('value.'):]
                new_node.inputs[input_name].default_value = val

            elif key.startswith('prop.'):
                prop_name = key[len('prop.'):]
                setattr(new_node, prop_name, val)

        input_block = Block.col_align_right(input_blocks)

        block = Block.row_align_center([input_block, new_node])
        block.outputs = new_node.outputs

        return block


def create_material(op, idx):
    """Create a Blender material for the glTF materials[idx]. If idx is the
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
    mc.bl_material = bpy.data.materials.new(material_name)
    mc.bl_material.use_nodes = True
    mc.tree = mc.bl_material.node_tree
    mc.links = mc.tree.links
    while mc.tree.nodes:
        mc.tree.nodes.remove(mc.tree.nodes[0])

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

    mc.adjoin({
        'node': 'OutputMaterial',
        'input.Surface': block,
    })

    return mc.bl_material


def create_emissive(mc):
    tex_block = None
    if 'emissiveTexture' in mc.material:
        tex_block = create_texture_block(mc.op, mc.idx, 'emissiveTexture', mc.tree, mc.material['emissiveTexture'])

    # TODO: emissive factor
    #@emissive_factor = mc.material.get('emissiveFactor', [0, 0, 0])

    if tex_block is None: return None

    return mc.adjoin({
        'node': 'Emission',
        'input.Color': tex_block,
    })


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
    }

    base_color_block = create_base_color(mc)
    if base_color_block:
        params['input.Base Color'] = base_color_block

    metal_roughness_block = create_metal_roughness(mc)
    if metal_roughness_block:
        params['output.G/input.Roughness'] = metal_roughness_block
        params['output.B/input.Metallic'] = metal_roughness_block

    normal_block = create_normal_block(mc)
    if normal_block:
        params['input.Normal'] = normal_block

    return mc.adjoin(params)


def create_base_color(mc):
    # TODO: baseColorFactor
    # TODO: vertex color
    if 'baseColorTexture' in mc.pbr:
        return create_texture_block(
            mc.op,
            mc.idx,
            'baseColorTexture',
            mc.tree,
            mc.pbr['baseColorTexture'],
        )
    else:
        return None


def create_metal_roughness(mc):
    # TODO: factors
    if 'metallicRoughnessTexture' in mc.pbr:
        tex_block = create_texture_block(
            mc.op,
            mc.idx,
            'metallicRoughnessTexture',
            mc.tree,
            mc.pbr['metallicRoughnessTexture'],
        )
        tex_block.img_node.color_space = 'NONE'

        return mc.adjoin({
            'node': 'SeparateRGB',
            'input.Image': tex_block,
        })

    else:
        return None



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
            'value.Strength': mc.material['normalTexture'].get('scale', 1),
            'input.Color': tex_block,
        })
    else:
        return None
