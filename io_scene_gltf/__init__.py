import json
import os
import struct

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from io_scene_gltf import buffer
from io_scene_gltf import material
from io_scene_gltf import mesh
from io_scene_gltf import node

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
        if idx not in self.buffers:
            self.buffers[idx] = buffer.create_buffer(self, idx)
        return self.buffers[idx]

    def get_buffer_view(self, idx):
        return buffer.create_buffer_view(self, idx)

    def get_accessor(self, idx):
        return buffer.create_accessor(self, idx)

    def get_material(self, idx):
        if idx not in self.materials:
            self.materials[idx] = material.create_material(self, idx)
        return self.materials[idx]

    def get_default_material(self):
        if not self.default_material:
            self.default_material = material.create_default_material()
        return self.default_material

    def get_mesh(self, idx):
        if idx not in self.meshes:
            self.meshes[idx] = mesh.create_mesh(self, idx)
        return self.meshes[idx]

    def get_camera(self, idx):
        if idx not in self.cameras:
            #TODO actually handle cameras
            camera = self.root['cameras'][idx]
            name = camera.get('name', 'cameras[%d]' % idx)
            self.cameras[idx] = bpy.data.cameras.new(name)
        return self.cameras[idx]

    def generate_scenes(self):
        if 'scenes' in self.root:
            for scene_idx in range(0, len(self.root['scenes'])):
                node.create_scene(self, scene_idx)

    def check_version(self):
        def string_to_version(s):
            try:
                version = [int(x) for x in s.split('.')]
            except Exception:
                version = None
            if version:
                return version
            else:
                raise Exception('unknown version: %s' % s)

        asset = self.root['asset']
        version = string_to_version(asset['version'])
        if version[0] != 2:
            raise Exception("unsupported version: %s" % version)
        #TODO handle minVersion

    def execute(self, context):
        filename = self.filepath
        self.base_path = os.path.dirname(filename)
        self.buffers = {}
        self.cameras = {}
        self.default_material = None
        self.materials = {}
        self.meshes = {}
        self.scenes = {}

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

        self.check_version()

        self.generate_scenes()

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
