import base64
import bpy
import json
import os
import struct
from mathutils import Vector
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.image_utils import load_image

bl_info = {
    "name": "glTF 2.0 Importer",
    "author": "Kristian Sons",
    "blender": (2, 71, 0),
    "location": "File > Import",
    "description": "",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export"
}


class ImportGLTF(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.gltf"
    bl_label = 'Import glTF'

    filename_ext = ".gltf"
    filter_glob = StringProperty(
        default="*.gltf",
        options={'HIDDEN'},
    )

    def get_buffer(self, idx):
        buffer = self.root['buffers'][idx]
        buffer_uri = buffer['uri']

        is_data_uri = buffer_uri[:37] == "data:application/octet-stream;base64,"
        if is_data_uri:
            return base64.b64decode(buffer_uri[37:])

        buffer_location = os.path.join(self.base_path, buffer_uri)

        if buffer_location in self.file_cache:
            return self.file_cache[buffer_location]

        print("Loading file", buffer_location)
        fp = open(buffer_location, "rb")
        bytes_read = fp.read()
        fp.close()

        self.file_cache[buffer_location] = bytes_read
        # print(len(bytes_read), buffer)
        return bytes_read

    def get_buffer_view(self, idx):
        buffer_view = self.root['bufferViews'][idx]
        buffer = self.get_buffer(buffer_view["buffer"])
        byte_offset = buffer_view["byteOffset"]
        byte_length = buffer_view["byteLength"]
        result = buffer[byte_offset:byte_offset + byte_length]
        stride = buffer_view.get('byteStride', None)
        # print("view", len(result))
        return (result, stride)

    def get_accessor(self, idx):
        accessor = self.root['accessors'][idx]

        fmt_char_lut = dict([
            (5120, "b"), # BYTE
            (5121, "B"), # UNSIGNED_BYTE
            (5122, "h"), # SHORT
            (5123, "H"), # UNSIGNED_SHORT
            (5125, "I"), # UNSIGNED_INT
            (5126, "f")  # FLOAT
        ])
        fmt_char = fmt_char_lut[accessor["componentType"]]
        num_components_lut = {
            "SCALAR": 1,
            "VEC2": 2,
            "VEC3": 3,
            "VEC4": 4,
            "MAT2": 4,
            "MAT3": 9,
            "MAT4": 16
        }
        num_components = num_components_lut[accessor["type"]]
        fmt = "<" + (fmt_char * num_components)
        count = accessor['count']

        if 'bufferView' not in accessor:
            if num_components == 1:
                return [0] * count
            else:
                return [tuple([0] * num_components)] * count
        #TODO sparse

        (buf, stride) = self.get_buffer_view(accessor['bufferView'])
        if not stride:
            # Tightly packed
            stride = struct.calcsize(fmt)

        off = accessor.get('byteOffset', 0)
        result = []
        while len(result) < count:
            attrib = struct.unpack_from(fmt, buf, offset = off)
            if num_components == 1:
                attrib = attrib[0]
            #TODO normalize
            result.append(attrib)
            off += stride

        return result

    def create_texture(self, idx, name, tree):
        texture = self.root['textures'][idx]
        source = self.root['images'][texture['source']]
        uri = source['uri']

        tex_image = tree.nodes.new("ShaderNodeTexImage")

        is_data_uri = uri[:5] == "data:"
        if is_data_uri:
            #TODO how do you load an image from memory?
            pass
        else:
            image_location = os.path.join(self.base_path, uri)
            tex_image.image = load_image(image_location)

        tex_image.label = name

        return tex_image

    def create_material(self, idx):
        material = self.root['materials'][idx]
        material_name = material.get('name', 'Material')

        if material_name in self.materials:
            return self.materials[material_name]

        print("Creating material", material_name)
        mat = bpy.data.materials.new(material_name)
        self.materials[material_name] = mat
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
                tex = self.create_texture(idx, 'baseColorTexture', tree)
                tex.location = -800, 50
                links.new(tex.outputs[0], diffuse.inputs[0])
                links.new(tex.outputs[0], metal_glossy.inputs[0])

            if 'metallicRoughnessTexture' in pbrMetallicRoughness:
                idx = pbrMetallicRoughness['metallicRoughnessTexture']['index']
                tex = self.create_texture(idx, 'metallicRoughnessTexture',
                                          tree)
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
            tex = self.create_texture(idx, 'emissiveTexture', tree)
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
            tex = self.create_texture(idx, 'normalTexture', tree)
            tex.color_space = 'NONE'
            tex.location = -1000, -100

            normal_map = tree.nodes.new('ShaderNodeNormalMap')
            normal_map.location = -800, -200

            links.new(tex.outputs[0], normal_map.inputs[1])
            for normal_input in normal_inputs:
                links.new(normal_map.outputs[0], normal_input)

        return mat

    def create_translation(self, obj, node):
        if 'translation' in node:
            obj.location = Vector(node['translation'])
        if 'scale' in node:
            obj.scale = Vector(node['scale'])

    def create_mesh(self, node, mesh):

        me = bpy.data.meshes.new(mesh.get('name', 'Mesh'))
        ob = bpy.data.objects.new(node.get('name', 'Node'), me)

        self.create_translation(ob, node)

        primitives = mesh['primitives'][0]
        material = self.create_material(primitives['material'])
        me.materials.append(material)
        indices = self.get_accessor(primitives['indices'])
        faces = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]

        attributes = primitives['attributes']
        positions = self.get_accessor(attributes['POSITION'])

        me.from_pydata(positions, [], faces)
        me.validate()

        for polygon in me.polygons:
            polygon.use_smooth = True

        normals = self.get_accessor(attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = normals[i]

        if 'TEXCOORD_0' in attributes:
            uvs = self.get_accessor(attributes['TEXCOORD_0'])
            me.uv_textures.new("TEXCOORD_0")
            for i, uv_loop in enumerate(me.uv_layers[0].data):
                uv = uvs[indices[i]]
                me.uv_layers[0].data[i].uv = (uv[0], -uv[1])

        me.update()
        return ob

    def create_group(self, node, parent):
        # print(node)
        if 'mesh' in node:
            ob = self.create_mesh(node, self.root['meshes'][node['mesh']])
        else:
            ob = bpy.data.objects.new(node.get('name', 'Node'), None)
            self.create_translation(ob, node)

        ob.parent = parent
        bpy.context.scene.objects.link(ob)
        bpy.context.scene.update()

        if 'children' in node:
            children = node['children']
            for idx in children:
                self.create_group(self.root['nodes'][idx], ob)

    def execute(self, context):
        filename = self.filepath
        self.base_path = os.path.dirname(filename)
        self.materials = {}
        self.file_cache = {}

        fp = open(filename, "r")
        self.root = root = json.load(fp)
        fp.close()

        scn = bpy.context.scene
        scn.render.engine = 'CYCLES'
        scn.world.use_nodes = True

        sceneIdx = root['scene']
        nodes = root['nodes']

        scene = root['scenes'][sceneIdx]

        [self.create_group(nodes[idx], None) for idx in scene['nodes']]
        return {'FINISHED'}


# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text="glTF JSON (.gltf)")


def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
