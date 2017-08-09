import os

import bpy
from bpy_extras.image_utils import load_image


def create_texture(op, idx, name, tree):
    texture = op.root['textures'][idx]
    source = op.root['images'][texture['source']]

    tex_image = tree.nodes.new("ShaderNodeTexImage")

    if 'uri' in source:
        uri = source['uri']
        is_data_uri = uri[:5] == "data:"
        if is_data_uri:
            #TODO how do you load an image from memory?
            pass
        else:
            image_location = os.path.join(op.base_path, uri)
            tex_image.image = load_image(image_location)

        tex_image.label = name
    else:
        #TODO load image from buffer view
        pass

    return tex_image


def create_material(op, idx):
    material = op.root['materials'][idx]
    material_name = material.get('name', 'materials[%d]' % idx)

    print("Creating material", material_name)
    mat = bpy.data.materials.new(material_name)
    op.materials[material_name] = mat
    mat.use_nodes = True
    tree = mat.node_tree
    links = tree.links

    for n in tree.nodes:
        tree.nodes.remove(n)

    normal_inputs = []

    mo = tree.nodes.new('ShaderNodeOutputMaterial')
    mo.location = 0, 0

    metal_mix = tree.nodes.new('ShaderNodeMixShader')
    metal_mix.location = -200, 0

    mix = tree.nodes.new('ShaderNodeMixShader')
    mix.location = -400, 0

    glossy = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossy.distribution = 'GGX'
    glossy.location = -600, -25
    normal_inputs.append(glossy.inputs[2])

    metal_glossy = tree.nodes.new('ShaderNodeBsdfGlossy')
    metal_glossy.distribution = 'GGX'
    metal_glossy.location = -400, -150
    normal_inputs.append(metal_glossy.inputs[2])

    diffuse = tree.nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.location = -600, 200
    normal_inputs.append(diffuse.inputs[2])

    fresnel = tree.nodes.new('ShaderNodeFresnel')
    fresnel.location = -600, 400

    links.new(metal_mix.outputs[0], mo.inputs[0])
    links.new(mix.outputs[0], metal_mix.inputs[1])
    links.new(metal_glossy.outputs[0], metal_mix.inputs[2])
    links.new(fresnel.outputs[0], mix.inputs[0])
    links.new(diffuse.outputs[0], mix.inputs[1])
    links.new(glossy.outputs[0], mix.inputs[2])

    if 'pbrMetallicRoughness' in material:
        pbrMetallicRoughness = material['pbrMetallicRoughness']
        if 'baseColorTexture' in pbrMetallicRoughness:
            idx = pbrMetallicRoughness['baseColorTexture']['index']
            tex = create_texture(op, idx, 'baseColorTexture', tree)
            tex.location = -800, 50
            links.new(tex.outputs[0], diffuse.inputs[0])
            links.new(tex.outputs[0], metal_glossy.inputs[0])

        if 'metallicRoughnessTexture' in pbrMetallicRoughness:
            idx = pbrMetallicRoughness['metallicRoughnessTexture']['index']
            tex = create_texture(op, idx, 'metallicRoughnessTexture', tree)
            tex.color_space = 'NONE'
            tex.location = -1000, 200

            separator = tree.nodes.new('ShaderNodeSeparateRGB')
            separator.location = -800, 200

            links.new(tex.outputs[0], separator.inputs[0])
            links.new(separator.outputs[0], metal_mix.inputs[0])
            links.new(separator.outputs[1], diffuse.inputs[1])
            links.new(separator.outputs[1], glossy.inputs[1])
            links.new(separator.outputs[1], metal_glossy.inputs[1])

    if 'emissiveTexture' in material:
        idx = material['emissiveTexture']['index']
        tex = create_texture(op, idx, 'emissiveTexture', tree)
        tex.location = -200, 250

        emissive = tree.nodes.new('ShaderNodeEmission')
        emissive.location = 0, 50

        add = tree.nodes.new('ShaderNodeAddShader')
        add.location = 200, 0
        mo.location = 400, 0

        links.new(tex.outputs[0], emissive.inputs[0])
        links.new(emissive.outputs[0], add.inputs[0])
        links.new(mo.inputs[0].links[0].from_socket, add.inputs[1])
        links.new(add.outputs[0], mo.inputs[0])

    if 'normalTexture' in material:
        idx = material['normalTexture']['index']
        tex = create_texture(op, idx, 'normalTexture', tree)
        tex.color_space = 'NONE'
        tex.location = -1000, -100

        normal_map = tree.nodes.new('ShaderNodeNormalMap')
        normal_map.location = -800, -200

        links.new(tex.outputs[0], normal_map.inputs[1])
        for normal_input in normal_inputs:
            links.new(normal_map.outputs[0], normal_input)

    return mat


def create_default_material():
    #TODO implement default material
    return bpy.data.materials.new('DefaultMaterial')
