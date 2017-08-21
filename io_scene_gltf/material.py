import base64
import os
import tempfile

import bpy
from bpy_extras.image_utils import load_image


def do_with_temp_file(contents, func):
    """Call func with the path to a temp file containing contents.

    The temp file will be deleted before this function returns.
    """
    path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        path = tmp.name
        tmp.write(contents)
        tmp.close() # Have to close so func can open it
        return func(path)
    finally:
        if path:
            os.remove(path)


def create_texture(op, idx, name, tree):
    texture = op.gltf['textures'][idx]
    source = op.gltf['images'][texture['source']]

    tex_image = tree.nodes.new("ShaderNodeTexImage")

    # Don't know how to load an image from memory, so if the data is
    # in a buffer or data URI, we'll write it to a temp file and use
    # this to load it from the temp file's path.
    # Yes, this is kind of a hack :)
    def load_from_temp(path):
        tex_image.image = load_image(path)

        # Need to pack the image into the .blend file or it will go
        # away as soon as the temp file is deleted.
        tex_image.image.pack() #TODO decide on tradeoff for using as_png

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
    tree = bpy.data.node_groups.new('metallicRoughnessPBR', 'ShaderNodeTree')
    inputs = tree.inputs
    outputs = tree.outputs
    links = tree.links

    for n in tree.nodes:
        tree.nodes.remove(n)

    # Crap, I did this function in camelCase. Of course it's the one with
    # a million variables. Stupid, stupid.
    #TODO make it snake_case

    baseColorFacInp = inputs.new('NodeSocketColor', 'baseColorFactor')
    baseColorTexInp = inputs.new('NodeSocketColor', 'baseColorTexture')
    metFacInp = inputs.new('NodeSocketFloat', 'metallicFactor')
    roughFacInp = inputs.new('NodeSocketFloat', 'roughnessFactor')
    metRoughTexInp = inputs.new('NodeSocketColor', 'metallicRoughnessTexture')
    vertColorInp = inputs.new('NodeSocketColor', 'Vertex Color')
    normalInp = inputs.new('NodeSocketNormal', 'Normal')

    baseColorFacInp.default_value = (1, 1, 1, 1)
    baseColorTexInp.default_value = (1, 1, 1, 1)
    metFacInp.default_value = 1
    roughFacInp.default_value = 1
    metRoughTexInp.default_value = (1, 1, 1, 1)
    vertColorInp.default_value = (1, 1, 1, 1)

    out = outputs.new('NodeSocketShader', 'Output Shader')

    inputNode = tree.nodes.new('NodeGroupInput')
    inputNode.location = -962, 183
    outputNode = tree.nodes.new('NodeGroupOutput')
    outputNode.location = 610, 224

    # Calculate output color (albedo)
    multColorNode1 = tree.nodes.new('ShaderNodeMixRGB')
    multColorNode1.location = -680, 466
    multColorNode1.blend_type = 'MULTIPLY'
    multColorNode1.inputs[0].default_value = 1
    links.new(inputNode.outputs[0], multColorNode1.inputs[1])
    links.new(inputNode.outputs[1], multColorNode1.inputs[2])
    multColorNode2 = tree.nodes.new('ShaderNodeMixRGB')
    multColorNode2.location = -496, 466
    multColorNode2.blend_type = 'MULTIPLY'
    multColorNode2.inputs[0].default_value = 1
    links.new(inputNode.outputs[5], multColorNode2.inputs[1])
    links.new(multColorNode1.outputs[0], multColorNode2.inputs[2])
    colorOutputLink = multColorNode2.outputs[0]

    # Calculate roughness and metalness
    separator = tree.nodes.new('ShaderNodeSeparateRGB')
    separator.location = -749, -130
    links.new(inputNode.outputs[4], separator.inputs[0])

    multRoughnessNode = tree.nodes.new('ShaderNodeMath')
    multRoughnessNode.location = -476, -50
    multRoughnessNode.operation = 'MULTIPLY'
    links.new(separator.outputs[1], multRoughnessNode.inputs[0])
    links.new(inputNode.outputs[3], multRoughnessNode.inputs[1])
    roughnessOutputLink = multRoughnessNode.outputs[0]

    multMetalnessNode = tree.nodes.new('ShaderNodeMath')
    multMetalnessNode.location = -476, -227
    multMetalnessNode.operation = 'MULTIPLY'
    links.new(separator.outputs[2], multMetalnessNode.inputs[0])
    links.new(inputNode.outputs[2], multMetalnessNode.inputs[1])
    metalnessOutputLink = multMetalnessNode.outputs[0]

    # First mix
    mixNode1 = tree.nodes.new('ShaderNodeMixShader')
    mixNode1.location = 226, 429

    fresnelNode = tree.nodes.new('ShaderNodeFresnel')
    fresnelNode.location = 14, 553
    links.new(inputNode.outputs[6], fresnelNode.inputs[1])

    diffuseNode = tree.nodes.new('ShaderNodeBsdfDiffuse')
    diffuseNode.location = 14, 427
    links.new(colorOutputLink, diffuseNode.inputs[0])
    links.new(roughnessOutputLink, diffuseNode.inputs[1])
    links.new(inputNode.outputs[6], diffuseNode.inputs[2])

    glossyNode = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossyNode.location = 14, 289
    links.new(roughnessOutputLink, glossyNode.inputs[1])
    links.new(inputNode.outputs[6], glossyNode.inputs[2])

    links.new(fresnelNode.outputs[0], mixNode1.inputs[0])
    links.new(diffuseNode.outputs[0], mixNode1.inputs[1])
    links.new(glossyNode.outputs[0], mixNode1.inputs[2])

    # Second mix
    mixNode2 = tree.nodes.new('ShaderNodeMixShader')
    mixNode2.location = 406, 239

    glossyNode2 = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossyNode2.location = 66, -114
    links.new(colorOutputLink, glossyNode2.inputs[0])
    links.new(roughnessOutputLink, glossyNode2.inputs[1])
    links.new(inputNode.outputs[6], glossyNode2.inputs[2])

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
    return create_material_from_object(op, material, material_name)


def create_material_from_object(op, material, material_name):
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
    mo.location = 365, -25
    links.new(group_node.outputs[0], mo.inputs[0])

    metalness = pbr_metallic_roughness.get('metallicFactor', 1)
    roughness = pbr_metallic_roughness.get('roughnessFactor', 1)
    base_color = pbr_metallic_roughness.get('baseColorFactor', [1, 1, 1, 1])

    group_node.inputs[0].default_value = base_color
    group_node.inputs[2].default_value = metalness
    group_node.inputs[3].default_value = roughness

    #TODO texCoord property
    if 'baseColorTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['baseColorTexture']['index']
        tex = create_texture(op, image_idx, 'baseColorTexture', tree)
        tex.location = -580, 200
        links.new(tex.outputs[0], group_node.inputs[1])
    if 'metallicRoughnessTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['metallicRoughnessTexture']['index']
        tex = create_texture(op, image_idx, 'metallicRoughnessTexture', tree)
        tex.location = -580, -150
        links.new(tex.outputs[0], group_node.inputs[4])
    if 'normalTexture' in material:
        image_idx = material['normalTexture']['index']
        tex = create_texture(op, image_idx, 'normalTexture', tree)
        tex.location = -342, -366
        tex.color_space = 'NONE'
        normal_map_node = tree.nodes.new('ShaderNodeNormalMap')
        normal_map_node.location = -150, -170
        links.new(tex.outputs[0], normal_map_node.inputs[1])
        links.new(normal_map_node.outputs[0], group_node.inputs[6])
        #TODO scale
    if 'emissiveTexture' in material:
        image_idx = material['emissiveTexture']['index']
        tex = create_texture(op, image_idx, 'emissiveTexture', tree)
        tex.location = 113, -291
        emission_node = tree.nodes.new('ShaderNodeEmission')
        emission_node.location = 284, -254
        add_node = tree.nodes.new('ShaderNodeAddShader')
        add_node.location = 357, -89
        links.new(tex.outputs[0], emission_node.inputs[0])
        links.new(group_node.outputs[0], add_node.inputs[0])
        links.new(emission_node.outputs[0], add_node.inputs[1])
        links.new(add_node.outputs[0], mo.inputs[0])
        mo.location = 547, -84
    #TODO occlusion texture

    return mat


def create_default_material(op):
    return create_material_from_object(op, {}, 'glTF Default Material')
