import json, os, struct

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper

from io_scene_gltf import animation, buffer, camera, material, mesh, scene, node_groups

bl_info = {
    'name': 'glTF 2.0 Importer',
    'author': 'Kristian Sons (ksons), scurest',
    'blender': (2, 79, 0),
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
EXTENSIONS = set((
    'KHR_materials_pbrSpecularGlossiness',
    'KHR_materials_unlit',
))


class ImportGLTF(bpy.types.Operator, ImportHelper):
    bl_idname = 'import_scene.gltf'
    bl_label = 'Import glTF'

    filename_ext = '.gltf'
    filter_glob = StringProperty(
        default='*.gltf;*.glb',
        options={'HIDDEN'},
    )

    import_under_current_scene = BoolProperty(
        name='Import contents under current scene',
        description=
            'When enabled, all the objects will be placed in the current '
            'scene and no scenes will be created.\n'
            'When disabled, scenes will be created to match the ones in the '
            'glTF file. Any object not in a scene will not be visible.',
        default=False,
    )
    smooth_polys = BoolProperty(
        name='Enable polygon smoothing',
        description=
            'Enable smoothing for all polygons in all imported meshes.',
        default=True,
    )
    framerate = FloatProperty(
        name='Frames/second',
        description=
            'Used for animation. The Blender frame corresponding to the glTF '
            'time t is computed as framerate * t.',
        default=60.0,
    )

    def execute(self, context):
        self.caches = {}

        self.load_config()
        self.load()
        self.check_version()
        self.check_required_extensions()

        material.compute_materials_using_color0(self)
        scene.create_scenes(self)
        animation.add_animations(self)

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
        contents = memoryview(contents)

        # Parse the header
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

        # The first chunk must be JSON
        json_chunk = parse_chunk(offset)
        if json_chunk['type'] != b'JSON':
            raise Exception('GLB: JSON chunk must be first')
        self.gltf = json.loads(
            json_chunk['data'].tobytes(),
            encoding='utf-8'
        )

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
        for ext in self.gltf.get('extensionsRequired', []):
            if ext not in EXTENSIONS:
                raise Exception('unsupported extension was required: %s' % ext)


    def load_config(self):
        """Load user-supplied options into instance vars."""
        keywords = self.as_keywords()
        self.import_under_current_scene = keywords['import_under_current_scene']
        self.smooth_polys = keywords['smooth_polys']
        self.framerate = keywords['framerate']



CREATE_FNS = {
    'buffer': buffer.create_buffer,
    'buffer_view': buffer.create_buffer_view,
    'accessor': buffer.create_accessor,
    'image': material.create_image,
    'material': material.create_material,
    'node_group': node_groups.create_group,
    'mesh': mesh.create_mesh,
    'camera': camera.create_camera,
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
