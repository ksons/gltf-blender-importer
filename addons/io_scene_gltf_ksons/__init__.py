import json
import os
import struct

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler

bl_info = {
    'name': "KSons' glTF 2.0 Importer",
    'author': 'Kristian Sons (ksons), scurest',
    'blender': (2, 79, 0),
    'version': (0, 4, 0),
    'location': "File > Import > KSons' glTF 2.0 (.glb/.gltf)",
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
    'EXT_property_animation',  # tentative, only material properties supported
    'KHR_lights_punctual',  # tentative until stabilized
    'KHR_materials_pbrSpecularGlossiness',
    'KHR_materials_unlit',
    'KHR_texture_transform',
    'MSFT_texture_dds',
))

from . import animation, buffer, camera, material, mesh, scene, light, load, vnode, node


class ImportGLTF(bpy.types.Operator, ImportHelper):
    """Load a glTF 2.0 file."""

    bl_idname = 'import_scene.gltf_ksons'
    bl_label = 'Import glTF'

    filename_ext = '.gltf'
    filter_glob = StringProperty(
        default='*.gltf;*.glb',
        options={'HIDDEN'},
    )

    import_under_current_scene = BoolProperty(
        name='Import contents under current scene',
        description='When enabled, all the objects will be placed in the current '
        'scene and no scenes will be created.\n'
        'When disabled, scenes will be created to match the ones in the '
        'glTF file. Any object not in a scene will not be visible.',
        default=True,
    )
    smooth_polys = BoolProperty(
        name='Enable polygon smoothing',
        description='Enable smoothing for all polygons in imported meshes. Suggest '
        'disabling for low-res models.',
        default=True,
    )
    bone_rotation_mode = EnumProperty(
        items=[
            ('NONE', "Don't change", ''),
            ('AUTO', 'Choose for me', ''),
            ('MANUAL', 'Choose manually', ''),
        ],
        name='Axis',
        description='Adjusts which local axis bones should point along. The axis they '
        'points along is always +Y. This option lets you rotate them so another '
        'axis becomes +Y.',
        default='AUTO',
    )
    bone_rotation_axis = EnumProperty(
        items=[
            ('+X', '+X', '+X'),
            ('-X', '-X', '-X'),
            ('-Y', '-Y', '-Y'),
            ('+Z', '+Z', '+Z'),
            ('-Z', '-Z', '-Z'),
        ],
        name='+Y to',
        description='If bones point the wrong way with the default value, enable '
        '"Display > Axes" for the Armature and look in Edit mode. '
        'You\'ll see that bones point along the local +Y axis. Decide '
        'which local axis they should point along and put it here.',
        default='+Z',
    )
    import_animations = BoolProperty(
        name='Import Animations',
        description='',
        default=True,
    )
    framerate = FloatProperty(
        name='Frames/second',
        description='Used for animation. The Blender frame corresponding to the glTF '
        'time t is computed as framerate * t.',
        default=60.0,
    )

    def execute(self, context):
        self.caches = {}
        self.material_texture_has_animated_transform = {}

        self.load_config()

        load.load(self)

        # Precomputations
        if self.import_animations:
            animation.gather_animation_info(self)
        material.compute_materials_using_color0(self)

        vnode.create_vtree(self)
        node.realize_vtree(self)
        scene.create_blender_scenes(self)
        if self.import_animations:
            animation.add_animations(self)

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout

        layout.prop(self, 'import_under_current_scene')

        col = layout.box().column()
        col.label('Mesh:', icon='MESH_DATA')
        col.prop(self, 'smooth_polys')

        col = layout.box().column()
        col.label('Bones:', icon='BONE_DATA')
        col.label('(Tweak if bones point wrong)')
        col.prop(self, 'bone_rotation_mode')
        if self.as_keywords()['bone_rotation_mode'] == 'MANUAL':
            col.prop(self, 'bone_rotation_axis')

        col = layout.box().column()
        col.label('Animation:', icon='OUTLINER_DATA_POSE')
        col.prop(self, 'import_animations')
        col.prop(self, 'framerate')

    def get(self, kind, id):
        cache = self.caches.setdefault(kind, {})
        if id in cache:
            return cache[id]
        else:
            CREATE_FNS = {
                'buffer': buffer.create_buffer,
                'buffer_view': buffer.create_buffer_view,
                'accessor': buffer.create_accessor,
                'image': material.create_image,
                'material': material.create_material,
                'node_group': material.create_group,
                'mesh': mesh.create_mesh,
                'camera': camera.create_camera,
                'light': light.create_light,
            }
            result = CREATE_FNS[kind](self, id)
            if type(result) == dict and result.get('do_not_cache_me', False):
                # Callee is requesting we not cache it
                result = result['result']
            else:
                cache[id] = result
            return result

    def load_config(self):
        """Load user-supplied options."""
        keywords = self.as_keywords()
        for opt in [
            'import_under_current_scene', 'smooth_polys',
            'import_animations', 'framerate', 'bone_rotation_mode',
            'bone_rotation_axis',
        ]:
            setattr(self, opt, keywords[opt])


# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text="KSons' glTF 2.0 (.glb/.gltf)")


def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == '__main__':
    register()
