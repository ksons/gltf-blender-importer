import base64
import os
import tempfile

import bpy
from bpy_extras.image_utils import load_image


def create_image(op, idx):
    image = op.gltf['images'][idx]

    img = None
    if 'uri' in image:
        uri = image['uri']
        is_data_uri = uri[:5] == 'data:'
        if is_data_uri:
            found_at = uri.find(';base64,')
            if found_at == -1:
                print("Couldn't read data URI; not base64?")
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
        # from memory, we'll write it to a temp file and load it from there.
        # Yes, this is a hack :)
        path = None
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            path = tmp.name
            tmp.write(buffer)
            tmp.close()
            img = load_image(path)
            img.pack()  # TODO: should we use as_png?
        finally:
            if path:
                os.remove(path)

    return img


def create_texture_node(op, idx, name, tree):
    texture = op.gltf['textures'][idx]

    #TODO: other properties

    tex_image = tree.nodes.new('ShaderNodeTexImage')
    tex_image.name = name
    tex_image.label = name
    tex_image.image = op.get('image', texture['source'])

    return tex_image


def create_material(op, idx):
    use_color0 = idx in op.materials_using_color0

    if idx == 'default_material':
        return create_material_from_properties(op, {}, 'gltf Default Material', use_color0)

    material = op.gltf['materials'][idx]
    material_name = material.get('name', 'materials[%d]' % idx)
    return create_material_from_properties(op, material, material_name, use_color0)


def create_material_from_properties(op, material, material_name, use_color0):
    pbr_metallic_roughness = material.get('pbrMetallicRoughness', {})

    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    tree = mat.node_tree
    links = tree.links

    for n in tree.nodes:
        tree.nodes.remove(n)

    group_node = tree.nodes.new('ShaderNodeGroup')
    group_node.location = 43, 68
    group_node.width = 255
    group_node.node_tree = op.get('node_group', 'glTF Metallic Roughness')

    mo = tree.nodes.new('ShaderNodeOutputMaterial')
    mo.location = 365, -25
    links.new(group_node.outputs[0], mo.inputs[0])


    group_node.inputs['MetallicFactor'].default_value = (
        pbr_metallic_roughness.get('metallicFactor', 1)
    )
    group_node.inputs['RoughnessFactor'].default_value = (
        pbr_metallic_roughness.get('roughnessFactor', 1)
    )
    group_node.inputs['BaseColorFactor'].default_value = (
        pbr_metallic_roughness.get('baseColorFactor', [1, 1, 1, 1])
    )

    # TODO texCoord property
    if 'baseColorTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['baseColorTexture']['index']
        tex = create_texture_node(op, image_idx, 'baseColorTexture', tree)
        tex.location = -307, 477
        links.new(tex.outputs[0], group_node.inputs["BaseColor"])
    if 'metallicRoughnessTexture' in pbr_metallic_roughness:
        image_idx = pbr_metallic_roughness['metallicRoughnessTexture']['index']
        tex = create_texture_node(op, image_idx, 'metallicRoughnessTexture', tree)
        tex.location = -505, 243
        tex.color_space = 'NONE'
        links.new(tex.outputs[0], group_node.inputs['MetallicRoughness'])
    if 'normalTexture' in material:
        image_idx = material['normalTexture']['index']
        tex = create_texture_node(op, image_idx, 'normalTexture', tree)
        tex.location = -635, -25
        tex.color_space = 'NONE'
        links.new(tex.outputs[0], group_node.inputs['Normal'])
        # TODO scale
    # TODO occlusion texture
    if 'emissiveTexture' in material:
        image_idx = material['emissiveTexture']['index']
        tex = create_texture_node(op, image_idx, 'emissiveTexture', tree)
        tex.location = -504, -592
        links.new(tex.outputs[0], group_node.inputs['Emissive'])

    if use_color0:
        node = tree.nodes.new('ShaderNodeAttribute')
        node.name = 'Vertex Color'
        node.location = -201, -620
        node.attribute_name = 'COLOR_0'
        links.new(node.outputs[0], group_node.inputs['COLOR_0'])
        group_node.inputs['Use COLOR_0'].default_value = 1.0


    # TODO: finish wiring everything up

    return mat


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
        primitives = mesh['primitives']
        for primitive in mesh['primitives']:
            if 'COLOR_0' in primitive['attributes']:
                mat = primitive.get('material', 'default_material')
                op.materials_using_color0.add(mat)
