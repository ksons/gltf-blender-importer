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
        # from memory, we'll write it to a temp file and load it from there.
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


    # Fill in all properties

    # Alpha mode affects many things...
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


    # A cache of nodes for different texcoords (eg. TEXCOORD_1)
    texcoord_nodes = {}
    # Where the put the next texcoord node
    # HACK: this is inside of an array for stupid Python reasons
    next_texcoord_node_y = [141]

    def texture_node(name, props):
        texture = op.gltf['textures'][props['index']]

        tex = tree.nodes.new('ShaderNodeTexImage')
        tex.name = name
        tex.label = name
        tex.image = op.get('image', texture['source'])
        tex.width = 216

        # Wire up any texcoord if necessary
        texcoord = props.get('texCoord', 0)
        if texcoord != 0:
            if texcoord not in texcoord_nodes:
                texcoord_node = tree.nodes.new('ShaderNodeUVMap') # TODO: is this the right kind of node?
                texcoord_node.uv_map = 'TEXCOORD_%d' % texcoord
                texcoord_node.location = -812, next_texcoord_node_y[0]
                next_texcoord_node_y[0] -= 120
                texcoord_nodes[texcoord] = texcoord_node
            links.new(texcoord_nodes[texcoord].outputs[0], tex.inputs[0])

        # Do the sampler properties
        # TODO: these don't map very easily to a Blender Image Texture Node so
        # there are lots of limitations :/

        if 'sampler' in texture:
            sampler = op.gltf['samplers'][texture['sampler']]
        else:
            sampler = {}

        NEAREST = 9728
        LINEAR = 9729
        AUTO_FILTER = LINEAR # which one to use if unspecified
        mag_filter = sampler.get('magFilter', AUTO_FILTER)
        # Just ignore the min-filter for now; we can't set them separately and
        # reporting when they differ is very noisy
        if mag_filter == NEAREST:
            tex.interpolation = 'Closest'
        elif mag_filter == LINEAR:
            tex.interpolation = 'Linear'
        else:
            print('unknown texture filter: %d' % mag_filter)

        CLAMP_TO_EDGE = 33071
        MIRRORED_REPEAT = 33648
        REPEAT = 10497
        wrap_s = sampler.get('wrapS', REPEAT)
        wrap_t = sampler.get('wrapT', REPEAT)
        if wrap_s != wrap_t:
            print('unsupported: wrap-s and wrap-t cannot be different (using wrap-s)')
        if wrap_s == CLAMP_TO_EDGE:
            tex.extension = 'EXTEND'
        elif wrap_s == MIRRORED_REPEAT:
            print('unsupported: textures cannot mirrored-repeat')
        elif wrap_s == REPEAT:
            tex.extension = 'REPEAT'
        else:
            print('unknown wrap mode: %d' % wrap_s)

        return tex

    if 'baseColorTexture' in pbr and 'BaseColor' in g.inputs:
        tex = texture_node('Base Color Texture', pbr['baseColorTexture'])
        tex.location = -566, 240
        tex.color_space = 'COLOR'
        links.new(tex.outputs[0], g.inputs['BaseColor'])
        if alpha_mode != 'OPAQUE':
            links.new(tex.outputs[1], g.inputs['Alpha'])

    if 'diffuseTexture' in pbr and 'Diffuse' in g.inputs:
        tex = texture_node('Diffuse Texture', pbr['diffuseTexture'])
        tex.location = -566, 240
        tex.color_space = 'COLOR'
        links.new(tex.outputs[0], g.inputs['Diffuse'])
        if alpha_mode != 'OPAQUE':
            links.new(tex.outputs[1], g.inputs['Alpha'])

    if 'metallicRoughnessTexture' in pbr and 'MetallicRoughness' in g.inputs:
        tex = texture_node('Metallic Roughness Texture', pbr['metallicRoughnessTexture'])
        tex.location = -315, 240
        tex.color_space = 'NONE'
        links.new(tex.outputs[0], g.inputs['MetallicRoughness'])

    if 'specularGlossinessTexture' in pbr and 'Specular' in g.inputs:
        tex = texture_node('Specular Glossiness Texture', pbr['specularGlossinessTexture'])
        tex.location = -315, 240
        tex.color_space = 'COLOR'
        links.new(tex.outputs[0], g.inputs['Specular'])
        links.new(tex.outputs[1], g.inputs['Glossiness'])

    if 'normalTexture' in material and 'Normal' in g.inputs:
        tex = texture_node('Normal Texture', material['normalTexture'])
        tex.location = -566, -37
        tex.color_space = 'NONE'
        links.new(tex.outputs[0], g.inputs['Normal'])
        if 'scale' in material['normalTexture']:
            g.inputs['NormalScale'].default_value = material['normalTexture']['scale']

    if 'occlusionTexture' in material and 'Occlusion' in g.inputs:
        tex = texture_node('Occlusion Texture', material['occlusionTexture'])
        tex.location = -315, -37
        tex.color_space = 'NONE'
        links.new(tex.outputs[0], g.inputs['Occlusion'])
        if 'strength' in material['occlusionTexture']:
            g.inputs['OcclusionStrength'].default_value = material['occlusionTexture']['strength']

    if 'emissiveTexture' in material and 'Emissive' in g.inputs:
        tex = texture_node('Emissive Texture', material['emissiveTexture'])
        tex.location = -441, -311
        tex.color_space = 'COLOR'
        links.new(tex.outputs[0], g.inputs['Emissive'])



    if use_color0:
        node = tree.nodes.new('ShaderNodeAttribute')
        node.name = 'Vertex Colors'
        node.location = -151, -384
        node.attribute_name = 'COLOR_0'
        links.new(node.outputs[0], g.inputs['COLOR_0'])
        g.inputs['Use COLOR_0'].default_value = 1.0


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
