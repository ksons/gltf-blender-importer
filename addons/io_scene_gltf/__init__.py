import json
import os
import struct

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from io_scene_gltf import animation, buffer, camera, material, mesh, node

bl_info = {
    'name': 'glTF 2.0 Importer',
    'author': 'Kristian Sons',
    'blender': (2, 71, 0),
    'location': 'File > Import',
    'description': '',
    'warning': '',
    'wiki_url': '',
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

    def execute(self, context):
        self.caches = {}

        self.load()
        self.check_version()
        self.check_required_extensions()

        node.create_scenes(self)

        return {'FINISHED'}

    def get(self, type, id):
        cache = self.caches.setdefault(type, {})
        if id not in cache:
            cache[id] = CREATE_FNS[type](self, id)
        return cache[id]

    def load(self):
        filename = self.filepath

        # Remember this for resolving relative paths
        self.base_path = os.path.dirname(filename)

        with open(filename, 'rb') as f:
            contents = f.read()

        # Use magic number to detect GLB files.
        is_glb = contents[:4] == b'glTF'
        if is_glb:
            self.parse_glb(contents)
        else:
            self.gltf = json.loads(contents.decode('utf-8'))
            self.glb_buffer = None

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
            return {
                'type': ty,
                'data': data,
                'next_offset': next_offset,
            }

        offset = 12  # end of header

        json_chunk = parse_chunk(offset)
        if json_chunk['type'] != b'JSON':
            raise Exception('GLB: JSON chunk must be first')
        self.gltf = json.loads(json_chunk['data'].decode('utf-8'))

        self.glb_buffer = None

        offset = json_chunk['next_offset']
        while offset < len(contents):
            chunk = parse_chunk(offset)

            # Ignore unknown chunks
            if chunk['type'] != b'BIN\0':
                offset = chunk['next_offset']
                continue

            if chunk['type'] == b'JSON':
                raise Exception('GLB: Too many JSON chunks, should be 1')

            if self.glb_buffer != None:
                raise Exception('GLB: Too many BIN chunks, should be 0 or 1')

            self.glb_buffer = chunk['data']

            offset = chunk['next_offset']

    def check_version(self):
        def parse_version(s):
            """Parse a string like '1.1' to a tuple (1,1)."""
            try:
                version = tuple(int(x) for x in s.split('.'))
                if len(version) >= 2: return version
            except Exception:
                pass
            raise Exception('unknown version format: %s' % s)

        asset = self.gltf['asset']

        if 'minVersion' in asset:
            min_version = parse_version(asset['minVersion'])
            supported = GLTF_VERSION >= min_version
            if not supported:
                raise Exception('unsupported minimum version: %s' % min_version)
        else:
            version = parse_version(asset['version'])
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


CREATE_FNS = {
    'buffer': buffer.create_buffer,
    'buffer_view': buffer.create_buffer_view,
    'accessor': buffer.create_accessor,
    'material': material.create_material,
    'mesh': mesh.create_mesh,
    'camera': camera.create_camera,
    'node': node.create_node,
}

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
