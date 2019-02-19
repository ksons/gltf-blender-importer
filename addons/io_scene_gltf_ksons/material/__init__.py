import json
import bpy
from .block import Block
from .texture import create_texture_block
from . import image, node_groups, precompute

# Re-exports
create_image = image.create_image
create_group = node_groups.create_group
material_precomputation = precompute.material_procomputation


def create_material(op, idx):
    """
    Create a Blender material for the glTF materials[idx]. If idx is the
    special value 'default_material', create a Blender material for the default
    glTF material instead.
    """
    mc = MaterialCreator()
    mc.op = op
    mc.idx = idx
    mc.liveness = op.material_infos[idx].liveness

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
    double_sided = mc.material.get('doubleSided', False) or mc.op.options['always_doublesided']
    if not double_sided and alpha_mode == 'OPAQUE':
        # Since we use alpha to simulate backface culling
        alpha_mode = 'MASK'

    if alpha_mode not in ['OPAQUE', 'MASK', 'BLEND']:
        print('unknown alpha mode %s' % alpha_mode)
        alpha_mode = 'OPAQUE'

    if getattr(bl_material, 'blend_method', None):
        bl_material.blend_method = {
            # glTF: Blender
            'OPAQUE': 'OPAQUE',
            'MASK': 'CLIP',
            'BLEND': 'BLEND',
        }[alpha_mode]
    else:
        bl_material.game_settings.alpha_blend = {
            # glTF: Blender
            'OPAQUE': 'OPAQUE',
            'MASK': 'CLIP',
            'BLEND': 'ALPHA',
        }[alpha_mode]

    # Set diffuse/specular color (for solid view)
    if 'baseColorFactor' in mc.pbr:
        diffuse_color = mc.pbr['baseColorFactor'][:len(bl_material.diffuse_color)]
        bl_material.diffuse_color = diffuse_color
    if 'diffuseFactor' in mc.pbr:
        diffuse_color = mc.pbr['diffuseFactor'][:len(bl_material.diffuse_color)]
        bl_material.diffuse_color = diffuse_color
    if 'specularFactor' in mc.pbr:
        specular_color = mc.pbr['specularFactor'][:len(bl_material.specular_color)]
        bl_material.specular_color = specular_color

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
        # Push things into a better position
        # [block] ->               -> [mix]
        #            [alpha block]
        alpha_block.pad_top(600)
        combined_block = Block.row_align_center([block, alpha_block])
        combined_block.outputs = \
            [block.outputs[0], alpha_block.outputs[0], alpha_block.outputs[1]]
        block = mc.adjoin({
            'node': 'MixShader',
            'output.0/input.2': combined_block,
            'output.1/input.Fac': combined_block,
            'output.2/input.1': combined_block,
        })

    mc.adjoin({
        'node': 'OutputMaterial',
        'input.Surface': block,
    }).center_at_origin()


def create_emissive(mc):
    if mc.type == 'unlit':
        return None

    block = None
    if 'emissiveTexture' in mc.material:
        block = create_texture_block(
            mc,
            'emissiveTexture',
            mc.material['emissiveTexture']
        )
        block.img_node.label = 'EMISSIVE'

    factor = mc.material.get('emissiveFactor', [0, 0, 0])

    if factor != [1, 1, 1] or 'emissiveFactor' in mc.liveness:
        if block:
            block = mc.adjoin({
                'node': 'MixRGB',
                'prop.blend_type': 'MULTIPLY',
                'input.Fac': Value(1),
                'input.Color1': block,
                'input.Color2': Value(factor + [1], record_to='emissiveFactor'),
            })
        else:
            if factor == [0, 0, 0] and 'emissiveFactor' not in mc.liveness:
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
    double_sided = mc.material.get('doubleSided', False) or mc.op.options['always_doublesided']

    if alpha_mode not in ['OPAQUE', 'MASK', 'BLEND']:
        alpha_mode = 'OPAQUE'

    # Create an empty block with the baseColor/diffuse texture's alpha
    if alpha_mode != 'OPAQUE' and getattr(mc, 'img_node', None):
        block = Block.empty(0, 0)
        block.outputs = [mc.img_node.outputs[1]]
    else:
        block = None

    # Alpha cutoff in MASK mode
    if alpha_mode == 'MASK' and block:
        alpha_cutoff = mc.material.get('alphaCutoff', 0.5)
        block = mc.adjoin({
            'node': 'Math',
            'prop.operation': 'GREATER_THAN',
            'input.0': block,
            'input.1': Value(alpha_cutoff, record_to='alphaCutoff'),
        })

    # Handle doublesidedness
    if not double_sided:
        sided_block = mc.adjoin({
            'node': 'NewGeometry',
        })
        sided_block = mc.adjoin({
            'node': 'Math',
            'prop.operation': 'SUBTRACT',
            'input.0': Value(1),
            'output.Backfacing/input.1': sided_block,
        })
        if block:
            block = mc.adjoin({
                'node': 'Math',
                'prop.operation': 'MULTIPLY',
                'input.1': block,
                'input.0': sided_block,
            })
        else:
            block = sided_block

    if block:
        transparent_block = mc.adjoin({
            'node': 'BsdfTransparent',
        })

        alpha_block = Block.col_align_right([block, transparent_block])
        alpha_block.outputs = [block.outputs[0], transparent_block.outputs[0]]
        block = alpha_block

    return block


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


def create_specGloss_pbr(mc):
    try:
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
        node = mc.tree.nodes.new('ShaderNodeEeveeSpecular')
        mc.tree.nodes.remove(node)
        has_specular_node = True
    except Exception:
        has_specular_node = False

    if has_specular_node:
        params = {
            'node': 'EeveeSpecular',
            'dim': (200, 540),
        }
    else:
        params = {
            'node': 'Group',
            'group': 'pbrSpecularGlossiness',
            'dim': (200, 540),
        }

    diffuse_block = create_diffuse(mc)
    if diffuse_block:
        params['input.Base Color'] = diffuse_block

    spec_rough_block = create_spec_roughness(mc)
    if spec_rough_block:
        params['output.0/input.Specular'] = spec_rough_block
        params['output.1/input.Roughness'] = spec_rough_block

    normal_block = create_normal_block(mc)
    if normal_block:
        params['input.Normal'] = normal_block

    if has_specular_node:
        occlusion_block = create_occlusion_block(mc)
        if occlusion_block:
            params['output.0/input.Ambient Occlusion'] = occlusion_block

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
            mc,
            'baseColorTexture',
            mc.pbr['baseColorTexture'],
        )
        block.img_node.label = 'BASE COLOR'
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
    if factor != [1, 1, 1, 1] or 'baseColorFactor' in mc.liveness:
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


def create_diffuse(mc):
    block = None
    if 'diffuseTexture' in mc.pbr:
        block = create_texture_block(
            mc,
            'diffuseTexture',
            mc.pbr['diffuseTexture'],
        )
        block.img_node.label = 'DIFFUSE'
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

    factor = mc.pbr.get('diffuseFactor', [1, 1, 1, 1])
    if factor != [1, 1, 1, 1] or 'diffuseFactor' in mc.liveness:
        if block:
            block = mc.adjoin({
                'node': 'MixRGB',
                'prop.blend_type': 'MULTIPLY',
                'input.Fac': Value(1),
                'input.Color1': block,
                'input.Color2': Value(factor, record_to='diffuseFactor'),
            })
        else:
            block = Value(factor, record_to='diffuseFactor')

    return block


def create_metal_roughness(mc):
    block = None
    if 'metallicRoughnessTexture' in mc.pbr:
        tex_block = create_texture_block(
            mc,
            'metallicRoughnessTexture',
            mc.pbr['metallicRoughnessTexture'],
        )
        tex_block.img_node.label = 'METALLIC ROUGHNESS'
        tex_block.img_node.color_space = 'NONE'

        block = mc.adjoin({
            'node': 'SeparateRGB',
            'input.Image': tex_block,
        })
        block.outputs = [block.outputs['B'], block.outputs['G']]

    metal_factor = mc.pbr.get('metallicFactor', 1)
    rough_factor = mc.pbr.get('roughnessFactor', 1)

    if not block:
        return [
            Value(metal_factor, record_to='metallicFactor'),
            Value(rough_factor, record_to='roughFactor'),
        ]

    if metal_factor != 1 or 'metallicFactor' in mc.liveness:
        metal_factor_options = {
            'node': 'Math',
            'prop.operation': 'MULTIPLY',
            'output.0/input.0': block,
            'input.1': Value(metal_factor, record_to='metallicFactor'),
        }
    else:
        metal_factor_options = {}
    if rough_factor != 1 or 'roughnessFactor' in mc.liveness:
        rough_factor_options = {
            'node': 'Math',
            'prop.operation': 'MULTIPLY',
            'output.1/input.0': block,
            'input.1': Value(rough_factor, record_to='roughnessFactor'),
        }
    else:
        rough_factor_options = {}

    return mc.adjoin_split(metal_factor_options, rough_factor_options, block)


def create_spec_roughness(mc):
    block = None
    if 'specularGlossinessTexture' in mc.pbr:
        block = create_texture_block(
            mc,
            'specularGlossinessTexture',
            mc.pbr['specularGlossinessTexture'],
        )
        block.img_node.label = 'SPECULAR GLOSSINESS'

    spec_factor = mc.pbr.get('specularFactor', [1, 1, 1]) + [1]
    gloss_factor = mc.pbr.get('glossinessFactor', 1)

    if not block:
        return [
            Value(spec_factor, record_to='specularFactor'),
            Value(gloss_factor, record_to='glossinessFactor'),
        ]

    if spec_factor != [1, 1, 1, 1] or 'specularFactor' in mc.liveness:
        spec_factor_options = {
            'node': 'MixRGB',
            'prop.operation': 'MULTIPLY',
            'input.Fac': Value(1),
            'output.Color/input.Color1': block,
            'input.Color2': Value(spec_factor, record_to='specularFactor'),
        }
    else:
        spec_factor_options = {}
    if gloss_factor != 1 or 'glossinessFactor' in mc.liveness:
        gloss_factor_options = {
            'node': 'Math',
            'prop.operation': 'MULTIPLY',
            'output.Alpha/input.0': block,
            'input.1': Value(gloss_factor, record_to='glossinessFactor'),
        }
    else:
        gloss_factor_options = {}

    block = mc.adjoin_split(spec_factor_options, gloss_factor_options, block)

    # Convert glossiness to roughness
    return mc.adjoin_split(None, {
        'node': 'Math',
        'prop.operation': 'SUBTRACT',
        'input.0': Value(1.0),
        'output.1/input.1': block,
    }, block)


def create_normal_block(mc):
    if 'normalTexture' in mc.material:
        tex_block = create_texture_block(
            mc,
            'normalTexture',
            mc.material['normalTexture'],
        )
        tex_block.img_node.label = 'NORMAL'
        tex_block.img_node.color_space = 'NONE'

        return mc.adjoin({
            'node': 'NormalMap',
            'prop.uv_map': 'TEXCOORD_%d' % mc.material['normalTexture'].get('texCoord', 0),
            'input.Strength': Value(mc.material['normalTexture'].get('scale', 1), record_to='normalTexture/scale'),
            'input.Color': tex_block,
        })
    else:
        return None


def create_occlusion_block(mc):
    if 'occlusionTexture' in mc.material:
        block = create_texture_block(
            mc,
            'occlusionTexture',
            mc.material['occlusionTexture'],
        )
        block.img_node.label = 'OCCLUSION'
        block.img_node.color_space = 'NONE'

        block = block = mc.adjoin({
            'node': 'SeparateRGB',
            'input.Image': block,
        })

        strength = mc.material['occlusionTexture'].get('strength', 1)
        if strength != 1 or 'occlusionTexture/strength' in mc.liveness:
            block = block = mc.adjoin({
                'node': 'Math',
                'prop.operation': 'MULTIPLY',
                'input.0': block,
                'input.1': Value(strength, record_to='occlusionTexture/strength'),
            })

        return block
    else:
        return None


class MaterialCreator:
    """
    Work-horse for creating nodes and automatically laying out blocks.
    """
    def new_node(self, opts):
        new_node = self.tree.nodes.new('ShaderNode' + opts['node'])
        new_node.width = 140
        new_node.height = 100

        if 'group' in opts:
            new_node.node_tree = self.op.get('node_group', opts['group'])

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

        return new_node, input_blocks

    def adjoin(self, opts):
        """
        Adjoins a new node. All the blocks that are used as inputs to it are
        laid out in a column to its left.

        [input1] -> [new_node]
        [input2] ->
        ...      ->
        """
        new_node, input_blocks = self.new_node(opts)

        input_block = Block.col_align_right(input_blocks)
        block = Block.row_align_center([input_block, new_node])
        block.outputs = new_node.outputs

        return block

    def adjoin_split(self, opts1, opts2, left_block):
        """
        Adjoins at-most-two new nodes (either or both can be missing). They are
        laid out in a column with left_block to their left. Return a block with
        two outputs; the first is the output of the first block, or the first
        output of left_block if missing; the second is the first output of the
        second block, or the second of left_block if missing.

        [left_block] -> [block1] ->
                     -> [block2] ->
        """
        if not opts1 and not opts2:
            return left_block

        outputs = []
        if opts1:
            block1, __input_blocks = self.new_node(opts1)
            outputs.append(block1.outputs[0])
        else:
            block1 = Block.empty()
            outputs.append(left_block.outputs[0])
        if opts2:
            block2, __input_blocks = self.new_node(opts2)
            outputs.append(block2.outputs[0])
        else:
            block2 = Block.empty()
            outputs.append(left_block.outputs[1])

        split_block = Block.col_align_right([block1, block2])
        block = Block.row_align_center([left_block, split_block])
        block.outputs = outputs

        return block

    def connect(self, connector, connector_key, node, socket_type, socket_key):
        """
        Connect a connector, which may be either a socket or a Value (or
        nothing) to a socket in the shader node tree.
        """
        if connector is None:
            return None

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
        # Record the data path to this socket in our material info so the
        # animation creator can find it to animate
        if value.record_to:
            self.op.material_infos[self.idx].paths[value.record_to] = (
                'nodes[' + json.dumps(node.name) + ']' +
                '.' + socket_type + '[' + json.dumps(socket_key) + ']' +
                '.default_value'
            )

    def connect_block(self, block, output_key, socket):
        self.links.new(block.outputs[output_key], socket)


class Value:
    """
    This is a helper class that tells the material creator to set the value of a
    socket rather than connect it to another socket. The record_to property, if
    present, is a key that the path to the socket should be remembered under.
    Remembering the path to where a Value got written into the node tree is used
    for animation importing (which needs to know where eg. the baseColorFactor
    wound up; it could be in a Multiply node or directly in the color socket of
    the Principled node, etc).
    """
    def __init__(self, value, record_to=''):
        self.value = value
        self.record_to = record_to
