import base64
import os
import tempfile

import bpy
from bpy_extras.image_utils import load_image

# This is a hack as it is not possible to access a "normal" slot via name or
# store it in a temporary variable
NORMAL = 6


def do_with_temp_file(contents, func):
    """Call func with the path to a temp file containing contents.

    The temp file will be deleted before this function returns.
    """
    path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        path = tmp.name
        tmp.write(contents)
        tmp.close()  # Have to close so func can open it
        return func(path)
    finally:
        if path:
            os.remove(path)


def create_texture(op, idx, name, tree):
    texture = op.gltf['textures'][idx]
    source = op.gltf['images'][texture['source']]

    tex_image = tree.nodes.new('ShaderNodeTexImage')

    # Don't know how to load an image from memory, so if the data is
    # in a buffer or data URI, we'll write it to a temp file and use
    # this to load it from the temp file's path.
    # Yes, this is kind of a hack :)
    def load_from_temp(path):
        tex_image.image = load_image(path)

        # Need to pack the image into the .blend file or it will go
        # away as soon as the temp file is deleted.
        tex_image.image.pack()  # TODO: decide on tradeoff for using as_png

    if 'uri' in source:
        uri = source['uri']
        is_data_uri = uri[:5] == 'data:'
        if is_data_uri:
            found_at = uri.find(';base64,')
            if found_at == -1:
                print("Couldn't read data URI; not base64?")
            else:
                buf = base64.b64decode(uri[found_at + 8:])
                do_with_temp_file(buf, load_from_temp)
        else:
            image_location = os.path.join(op.base_path, uri)
            tex_image.image = load_image(image_location)

        tex_image.label = name
    else:
        buf, _stride = op.get_buffer_view(source['bufferView'])
        do_with_temp_file(buf, load_from_temp)

    return tex_image


def create_pbr_group():
    """Create a node group for metallic-roughness PBR."""

    # XXX IDEA
    # Use rna2xml to serialize the PBR group in KhronosGroup/glTF-Blender-Exporter
    # and just import it here and get rid of this whole mess!

    tree = bpy.data.node_groups.new('metallicRoughnessPBR', 'ShaderNodeTree')
    inputs = tree.inputs
    outputs = tree.outputs
    links = tree.links

    for n in tree.nodes:
        tree.nodes.remove(n)

    # Crap, I did this function in camelCase. Of course it's the one with
    # a million variables. Stupid, stupid.
    # TODO: make it snake_case

    baseColorFacInp = inputs.new('NodeSocketColor', 'baseColorFactor')
    baseColorTexInp = inputs.new('NodeSocketColor', 'baseColorTexture')
    metFacInp = inputs.new('NodeSocketFloat', 'metallicFactor')
    roughFacInp = inputs.new('NodeSocketFloat', 'roughnessFactor')
    metRoughTexInp = inputs.new('NodeSocketColor', 'metallicRoughnessTexture')
    vertColorInp = inputs.new('NodeSocketColor', 'Vertex Color')
    inputs.new('NodeSocketNormal', 'Normal')

    baseColorFacInp.default_value = (1, 1, 1, 1)
    baseColorTexInp.default_value = (1, 1, 1, 1)
    metFacInp.default_value = 1
    roughFacInp.default_value = 1
    metRoughTexInp.default_value = (1, 1, 1, 1)
    vertColorInp.default_value = (1, 1, 1, 1)

    outputs.new('NodeSocketShader', 'Output Shader')

    inputNode = tree.nodes.new('NodeGroupInput')
    inputNode.location = -962, 183
    outputNode = tree.nodes.new('NodeGroupOutput')
    outputNode.location = 610, 224

    # Calculate output color (albedo)
    multColorNode1 = tree.nodes.new('ShaderNodeMixRGB')
    multColorNode1.location = -680, 466
    multColorNode1.blend_type = 'MULTIPLY'
    multColorNode1.inputs['Fac'].default_value = 1
    links.new(inputNode.outputs['baseColorFactor'],
              multColorNode1.inputs['Color1'])
    links.new(inputNode.outputs['baseColorTexture'],
              multColorNode1.inputs['Color2'])

    multColorNode2 = tree.nodes.new('ShaderNodeMixRGB')
    multColorNode2.location = -496, 466
    multColorNode2.blend_type = 'MULTIPLY'
    multColorNode2.inputs['Fac'].default_value = 1
    links.new(inputNode.outputs['Vertex Color'],
              multColorNode2.inputs['Color1'])
    links.new(multColorNode1.outputs['Color'], multColorNode2.inputs['Color2'])
    colorOutputLink = multColorNode2.outputs['Color']

    # Calculate roughness and metalness
    separator = tree.nodes.new('ShaderNodeSeparateRGB')
    separator.location = -749, -130
    links.new(
        inputNode.outputs['metallicRoughnessTexture'], separator.inputs['Image'])

    multRoughnessNode = tree.nodes.new('ShaderNodeMath')
    multRoughnessNode.location = -476, -50
    multRoughnessNode.operation = 'MULTIPLY'
    links.new(separator.outputs['G'], multRoughnessNode.inputs[0])
    links.new(inputNode.outputs['metallicFactor'], multRoughnessNode.inputs[1])
    roughnessOutputLink = multRoughnessNode.outputs['Value']

    multMetalnessNode = tree.nodes.new('ShaderNodeMath')
    multMetalnessNode.location = -476, -227
    multMetalnessNode.operation = 'MULTIPLY'
    links.new(separator.outputs['B'], multMetalnessNode.inputs[0])
    links.new(inputNode.outputs['roughnessFactor'],
              multMetalnessNode.inputs[1])
    metalnessOutputLink = multMetalnessNode.outputs['Value']

    # First mix
    mixNode1 = tree.nodes.new('ShaderNodeMixShader')
    mixNode1.location = 226, 429

    fresnelNode = tree.nodes.new('ShaderNodeFresnel')
    fresnelNode.location = 14, 553
    links.new(inputNode.outputs[NORMAL], fresnelNode.inputs[1])

    diffuseNode = tree.nodes.new('ShaderNodeBsdfDiffuse')
    diffuseNode.location = 14, 427
    links.new(colorOutputLink, diffuseNode.inputs['Color'])
    links.new(roughnessOutputLink, diffuseNode.inputs['Roughness'])
    links.new(inputNode.outputs[NORMAL], diffuseNode.inputs['Normal'])

    glossyNode = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossyNode.location = 14, 289
    links.new(roughnessOutputLink, glossyNode.inputs['Roughness'])
    links.new(inputNode.outputs[NORMAL], glossyNode.inputs['Normal'])

    links.new(fresnelNode.outputs[0], mixNode1.inputs[0])
    links.new(diffuseNode.outputs[0], mixNode1.inputs[1])
    links.new(glossyNode.outputs[0], mixNode1.inputs[2])

    # Second mix
    mixNode2 = tree.nodes.new('ShaderNodeMixShader')
    mixNode2.location = 406, 239

    glossyNode2 = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossyNode2.location = 66, -114
    links.new(colorOutputLink, glossyNode2.inputs['Color'])
    links.new(roughnessOutputLink, glossyNode2.inputs['Roughness'])
    links.new(inputNode.outputs[NORMAL], glossyNode2.inputs['Normal'])

    links.new(metalnessOutputLink, mixNode2.inputs[0])
    links.new(mixNode1.outputs[0], mixNode2.inputs[1])
    links.new(glossyNode2.outputs[0], mixNode2.inputs[2])

    links.new(mixNode2.outputs[0], outputNode.inputs[0])

    return tree


def get_pbr_group(op):
    if not op.pbr_group:
        op.pbr_group = create_pbr_group()
    return op.pbr_group


def create_material(op, idx):
    material = op.gltf['materials'][idx]
    material_name = material.get('name', 'materials[%d]' % idx)
    return create_material_from_properties(op, material, material_name)


def create_material_from_properties(op, material, material_name):
    pbr_metallic_roughness = material.get('pbrMetallicRoughness', {})

    mat = bpy.data.materials.new(material_name)
    op.materials[material_name] = mat
    mat.use_nodes = True
    tree = mat.node_tree
    links = tree.links

    for n in tree.nodes:
        tree.nodes.remove(n)

    group = get_pbr_group(op)
    group_node = tree.nodes.new('ShaderNodeGroup')
    group_node.location = 43, 68
    group_node.node_tree = group

    mo = tree.nodes.new('ShaderNodeOutputMaterial')
    mo.location = 420, -25
    final_output = group_node.outputs[0]

    metalness = pbr_metallic_roughness.get('metallicFactor', 1)
    roughness = pbr_metallic_roughness.get('roughnessFactor', 1)
    base_color = pbr_metallic_roughness.get('baseColorFactor', [1, 1, 1, 1])

    group_node.inputs['baseColorFactor'].default_value = base_color
    group_node.inputs['metallicFactor'].default_value = metalness
    group_node.inputs['roughnessFactor'].default_value = roughness

    base_color_texture = None
    # TODO texCoord property
    if 'baseColorTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['baseColorTexture']['index']
        base_color_texture = create_texture(
            op, image_idx, 'baseColorTexture', tree)
        base_color_texture.location = -580, 200
        links.new(
            base_color_texture.outputs['Color'], group_node.inputs['baseColorTexture'])

    if 'metallicRoughnessTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['metallicRoughnessTexture']['index']
        tex = create_texture(op, image_idx, 'metallicRoughnessTexture', tree)
        tex.location = -580, -150
        links.new(tex.outputs[0],
                  group_node.inputs['metallicRoughnessTexture'])

    if 'normalTexture' in material:
        image_idx = material['normalTexture']['index']
        tex = create_texture(op, image_idx, 'normalTexture', tree)
        tex.location = -342, -366
        tex.color_space = 'NONE'
        normal_map_node = tree.nodes.new('ShaderNodeNormalMap')
        normal_map_node.location = -150, -170
        links.new(tex.outputs['Color'], normal_map_node.inputs['Color'])
        links.new(normal_map_node.outputs[0], group_node.inputs[NORMAL])
        # TODO scale

    if 'emissiveTexture' in material:
        image_idx = material['emissiveTexture']['index']
        tex = create_texture(op, image_idx, 'emissiveTexture', tree)
        tex.location = 113, -291
        emission_node = tree.nodes.new('ShaderNodeEmission')
        emission_node.location = 284, -254
        add_node = tree.nodes.new('ShaderNodeAddShader')
        add_node.location = 357, -89
        links.new(tex.outputs[0], emission_node.inputs[0])
        links.new(final_output, add_node.inputs[0])
        links.new(emission_node.outputs[0], add_node.inputs[1])
        final_output = add_node.outputs[0]
        mo.location = 547, -84
    # TODO occlusion texture

    alpha_mode = material.get("alphaMode", "OPAQUE")
    if alpha_mode == "BLEND" and base_color_texture:

        transparent_node = tree.nodes.new('ShaderNodeBsdfTransparent')
        transparent_node.location = 43, -240

        mix_node = tree.nodes.new('ShaderNodeMixShader')
        mix_node.location = 250, -151

        links.new(base_color_texture.outputs['Alpha'], mix_node.inputs['Fac'])
        links.new(transparent_node.outputs[0], mix_node.inputs[1])
        links.new(final_output, mix_node.inputs[2])

        final_output = mix_node.outputs[0]

    links.new(final_output, mo.inputs[0])

    return mat


def create_default_material(op):
    return create_material_from_properties(op, {}, 'glTF Default Material')
