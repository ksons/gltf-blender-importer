import base64
import bpy
import json
import os
import struct

from mathutils import Vector
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.image_utils import load_image

from io_scene_gltf.mesh import create_mesh

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
        default="*.gltf;*.glb",
        options={'HIDDEN'},
    )

    def get_buffer(self, idx):
        buffer = self.root['buffers'][idx]

        if self.glb_buffer and idx == 0 and 'uri' not in buffer:
            return self.glb_buffer

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
        byte_offset = buffer_view.get("byteOffset", 0)
        byte_length = buffer_view["byteLength"]
        result = buffer[byte_offset:byte_offset + byte_length]
        stride = buffer_view.get('byteStride', None)
        # print("view", len(result))
        return (result, stride)

    def get_accessor(self, idx):
        accessor = self.root['accessors'][idx]

        count = accessor['count']
        fmt_char_lut = dict([
            (5120, "b"), # BYTE
            (5121, "B"), # UNSIGNED_BYTE
            (5122, "h"), # SHORT
            (5123, "H"), # UNSIGNED_SHORT
            (5125, "I"), # UNSIGNED_INT
            (5126, "f")  # FLOAT
        ])
        fmt_char = fmt_char_lut[accessor['componentType']]
        component_size = struct.calcsize(fmt_char)
        num_components_lut = {
            "SCALAR": 1,
            "VEC2": 2,
            "VEC3": 3,
            "VEC4": 4,
            "MAT2": 4,
            "MAT3": 9,
            "MAT4": 16
        }
        num_components = num_components_lut[accessor['type']]
        fmt = "<" + (fmt_char * num_components)
        default_stride = struct.calcsize(fmt)

        # Special layouts for certain formats; see the section about
        # data alignment in the glTF 2.0 spec.
        if accessor['type'] == 'MAT2' and component_size == 1:
            fmt = "<" + \
                (fmt_char * 2) + "xx" + \
                (fmt_char * 2)
            default_stride = 8
        elif accessor['type'] == 'MAT3' and component_size == 1:
            fmt = "<" + \
                (fmt_char * 3) + "x" + \
                (fmt_char * 3) + "x" + \
                (fmt_char * 3)
            default_stride = 12
        elif accessor['type'] == 'MAT3' and component_size == 2:
            fmt = "<" + \
                (fmt_char * 3) + "xx" + \
                (fmt_char * 3) + "xx" + \
                (fmt_char * 3)
            default_stride = 24

        normalize = None
        if 'normalized' in accessor and accessor['normalized']:
            # Technically, there are two slightly different normalization
            # formulas used in OpenGL for signed integers.
            #   1) max(x/(2^b - 1), -1)
            #   2) (2x + 1)/(2^b - 1)
            # (1) is used by recent OpenGL versions. (2) is used by older
            # versions, including WebGL (the problem with (2) is it is
            # never zero). We'll use (2) since it's what WebGL should do.
            normalize_lut = dict([
                (5120, lambda x: (2*x + 1) / (2**8 - 1)), # BYTE
                (5121, lambda x: x / (2*8 - 1)), # UNSIGNED_BYTE
                (5122, lambda x: (2*x + 1) / (2**16 - 1)), # SHORT
                (5123, lambda x: x / (2*16 - 1)), # UNSIGNED_SHORT
                (5125, lambda x: x / (2**32 - 1)), # UNSIGNED_INT
            ])
            normalize = normalize_lut[accessor['componentType']]

        if 'bufferView' in accessor:
            (buf, stride) = self.get_buffer_view(accessor['bufferView'])
            stride = stride or default_stride
        else:
            stride = default_stride
            buf = [0] * (stride * count)

        if 'sparse' in accessor:
            #TODO sparse
            raise Exception("sparse accessors unsupported")

        off = accessor.get('byteOffset', 0)
        result = []
        while len(result) < count:
            elem = struct.unpack_from(fmt, buf, offset = off)
            if normalize:
                elem = tuple([normalize(x) for x in elem])
            if num_components == 1:
                elem = elem[0]
            result.append(elem)
            off += stride

        return result

    def create_texture(self, idx, name, tree):
        texture = self.root['textures'][idx]
        source = self.root['images'][texture['source']]

        tex_image = tree.nodes.new("ShaderNodeTexImage")

        if 'uri' in source:
            uri = source['uri']
            is_data_uri = uri[:5] == "data:"
            if is_data_uri:
                #TODO how do you load an image from memory?
                pass
            else:
                image_location = os.path.join(self.base_path, uri)
                tex_image.image = load_image(image_location)

            tex_image.label = name
        else:
            #TODO load image from buffer view
            pass

        return tex_image

    def get_material(self, idx):
        material = self.root['materials'][idx]
        material_name = material.get('name', 'materials[%d]' % idx)

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

    def get_default_material(self):
        #TODO implement default material
        if not self.default_material:
            self.default_material = bpy.data.materials.new('DefaultMaterial')
        return self.default_material

    def create_translation(self, obj, node):
        if 'translation' in node:
            obj.location = Vector(node['translation'])
        if 'scale' in node:
            obj.scale = Vector(node['scale'])

    def get_mesh(self, idx):
        if idx not in self.meshes:
            self.meshes[idx] = create_mesh(self, idx)
        return self.meshes[idx]

    def create_object(self, idx, parent, scene):
        node = self.root['nodes'][idx]
        name = node.get('name', 'nodes[%d]' % idx)
        ob = bpy.data.objects.new(name, None)

        if 'mesh' in node:
            mesh_ob = bpy.data.objects.new(name + '.mesh', self.get_mesh(node['mesh']))
            mesh_ob.parent = ob
            scene.objects.link(mesh_ob)
        #TODO handle skin/camera

        self.create_translation(ob, node)

        ob.parent = parent
        bpy.context.scene.objects.link(ob)
        scene.update()

        if 'children' in node:
            children = node['children']
            for idx in children:
                self.create_object(idx, ob, scene)

    def create_scene(self, idx):
        scene = self.root['scenes'][idx]
        name = scene.get('name', 'scene[%d]' % idx)

        bpy.ops.scene.new(type = 'NEW')
        scn = bpy.context.scene
        scn.name = name
        scn.render.engine = 'CYCLES'
        # scn.world.use_nodes = True

        for root_idx in scene.get('nodes', []):
            self.create_object(root_idx, None, scn)

        scn.update()

        self.scenes[idx] = scn

    def execute(self, context):
        filename = self.filepath
        self.base_path = os.path.dirname(filename)
        self.materials = {}
        self.default_material = None
        self.meshes = {}
        self.scenes = {}
        self.file_cache = {}

        fp = open(filename, "rb")
        contents = fp.read()
        fp.close()

        # Use magic number to detect GLB files.
        is_glb = contents[:4] == b"glTF"

        if is_glb:
            print("Detected GLB file")

            version = struct.unpack_from("<I", contents, offset = 4)[0]
            if version != 2:
                raise Exception("GLB: version not supported: %d" % version)

            json_length = struct.unpack_from("<I", contents, offset = 12)[0]
            end_of_json = 20 + json_length
            self.root = json.loads(contents[20 : end_of_json])

            # Check for BIN chunk
            if len(contents) > end_of_json:
                bin_length = struct.unpack_from("<I", contents, offset = end_of_json)[0]
                end_of_bin = end_of_json + 8 + bin_length
                self.glb_buffer = contents[end_of_json + 8 : end_of_bin]
            else:
                self.glb_buffer = None
        else:
            self.root = json.loads(contents)
            self.glb_buffer = None

        if 'scenes' in self.root:
            for scene_idx in range(0, len(self.root['scenes'])):
                self.create_scene(scene_idx)

        if 'scene' in self.root:
            bpy.context.screen.scene = self.scenes[self.root['scene']]

        return {'FINISHED'}


# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text="glTF JSON (.gltf/.glb)")


def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
