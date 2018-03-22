import json
import os
import struct

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from io_scene_gltf import animation, buffer, material, mesh, node, camera

bl_info = {
    'name': 'glTF 2.0 Importer',
    'author': 'Kristian Sons (ksons), scurest',
    'blender': (2, 71, 0),
    'version': (0, 3, 0),
    'location': 'File > Import > glTF JSON (.gltf/.glb)',
    'description': 'Importer for the glTF 2.0 file format.',
    'warning': '',
    'wiki_url': 'https://github.com/ksons/gltf-blender-importer/blob/master/README.md',
    'tracker_url': 'https://github.com/ksons/gltf-blender-importer/issues',
    'category': 'Import-Export'
}


# Supported glTF version
GLTF_VERSION = (2, 0)
# Supported extensions
EXTENSIONS = set()


class ImportGLTF(bpy.types.Operator, ImportHelper):
    bl_idname = 'import_scene.gltf'
    bl_label = 'Import glTF'

    filename_ext = '.gltf'
    filter_glob = StringProperty(
        default='*.gltf;*.glb',
        options={'HIDDEN'},
    )

    def get_buffer(self, idx):
        if idx not in self.buffers:
            self.buffers[idx] = buffer.create_buffer(self, idx)
        return self.buffers[idx]

    def get_buffer_view(self, idx):
        if idx not in self.buffer_views:
            self.buffer_views[idx] = buffer.create_buffer_view(self, idx)
        return self.buffer_views[idx]

    def get_accessor(self, idx):
        if idx not in self.accessors:
            self.accessors[idx] = buffer.create_accessor(self, idx)
        return self.accessors[idx]

    def get_material(self, idx):
        if idx not in self.materials:
            self.materials[idx] = material.create_material(self, idx)
        return self.materials[idx]

    def get_default_material(self):
        if not self.default_material:
            self.default_material = material.create_default_material(self)
        return self.default_material

    def get_mesh(self, idx):
        if idx not in self.meshes:
            self.meshes[idx] = mesh.create_mesh(self, idx)
        return self.meshes[idx]

    def get_camera(self, idx):
        if idx not in self.cameras:
            self.cameras[idx] = camera.create_camera(self, idx)
        return self.cameras[idx]

    def generate_actions(self):
        if 'animations' in self.gltf:
            for idx in range(0, len(self.gltf['animations'])):
                animation.create_action(self, idx)

    def check_version(self):
        def str_to_version(s):
            try:
                version = tuple(int(x) for x in s.split('.'))
                if len(version) >= 2:
                    return version
            except Exception:
                pass

            raise Exception('unknown version format: %s' % s)

        asset = self.gltf['asset']

        if 'minVersion' in asset:
            min_version = str_to_version(asset['minVersion'])
            supported = GLTF_VERSION >= min_version
            if not supported:
                raise Exception('unsupported minimum version: %s' % min_version)
        else:
            version = str_to_version(asset['version'])
            # Check only major version; we should be backwards- and forwards-compatible
            supported = version[0] == GLTF_VERSION[0]
            if not supported:
                raise Exception('unsupported version: %s' % version)

    def check_required_extensions(self):
        # TODO: the below works but it will make the tests fails.
        # Can be uncommented when KhronosGroup/glTF-Sample-Models#144
        # is closed OR we implement pbrSpecularGlossiness.
        pass

        # for ext in self.gltf.get('extensionsRequired', []):
        #    if ext not in EXTENSIONS:
        #        raise Exception('unsupported extension was required: %s' % ext)

    def load(self):
        filename = self.filepath
        self.base_path = os.path.dirname(filename)

        with open(filename, 'rb') as f:
            contents = f.read()

        # Use magic number to detect GLB files.
        is_glb = contents[:4] == b'glTF'

        if is_glb:
            self.parse_glb(contents)
        else:
            self.gltf = json.loads(contents.decode('utf-8'))

    def parse_glb(self, contents):
        header = struct.unpack_from('<4sII', contents)
        glb_version = header[1]
        if glb_version != 2:
            raise Exception('GLB: version not supported: %d' % glb_version)

        def parse_chunk(offset):
            header = struct.unpack_from('<I4s', contents, offset=offset)
            data_len = header[0]
            ty = header[1]
            data = contents[offset + 8: offset + 8 + data_len]
            next_offset = offset + 8 + data_len
            return {'type': ty, 'data': data, 'next_offset': next_offset}

        offset = 12  # end of header

        json_chunk = parse_chunk(offset)
        if json_chunk['type'] != b'JSON':
            raise Exception('GLB: JSON chunk must be first')
        self.gltf = json.loads(json_chunk['data'].decode('utf-8'))

        offset = json_chunk['next_offset']

        while offset < len(contents):
            chunk = parse_chunk(offset)

            # Ignore unknown chunks
            if chunk['type'] != b'BIN\0':
                offset = chunk['next_offset']
                continue

            if chunk['type'] == b'JSON':
                raise Exception('GLB: Too many JSON chunks, should be 1')

            if self.glb_buffer:
                raise Exception('GLB: Too many BIN chunks, should be 0 or 1')

            self.glb_buffer = chunk['data']

            offset = chunk['next_offset']

    def execute(self, context):
        self.glb_buffer = None
        self.buffers = {}
        self.buffer_views = {}
        self.accessors = {}
        self.cameras = {}
        self.default_material = None
        self.pbr_group = None
        self.materials = {}
        self.meshes = {}
        self.scenes = {}
        # Indices of the root nodes
        self.root_idxs = []
        # Maps the index of a root node to the objects in that tree
        self.root_to_objects = {}
        # Maps a node index to the corresponding bone's name
        self.node_to_bone_name = {}

        self.load()

        self.check_version()
        self.check_required_extensions()

        node.create_hierarchy(self)
        self.generate_actions()

        if 'scene' in self.gltf and bpy.context.screen:
            bpy.context.screen.scene = self.scenes[self.gltf['scene']]

        return {'FINISHED'}


# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text='glTF JSON (.gltf/.glb)')


def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == '__main__':
    register()
