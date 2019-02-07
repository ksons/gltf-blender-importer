import json
import os
import struct

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper

bl_info = {
    'name': "KSons' glTF 2.0 Importer",
    'author': 'Kristian Sons (ksons), scurest',
    'blender': (2, 80, 0),
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
    'KHR_lights_punctual',
    'KHR_materials_pbrSpecularGlossiness',
    'KHR_materials_unlit',
    'KHR_texture_transform',
    'MSFT_texture_dds',
))

from .importer import Importer

class ImportGLTF(bpy.types.Operator, ImportHelper):
    """Load a glTF 2.0 file."""

    bl_idname = 'import_scene.gltf_ksons'
    bl_label = 'Import glTF'

    filename_ext = '.gltf'
    filter_glob = StringProperty(
        default='*.gltf;*.glb',
        options={'HIDDEN'},
    )

    global_scale = FloatProperty(
        name='Global Scale',
        description=(
            'Scales all linear distances by the given factor. Use to change '
            'units (glTF is in meters)'
        ),
        default=1.0,
    )
    axis_conversion = EnumProperty(
        items=[
            ('BLENDER_UP', 'Blender Up (+Z)', ''),
            ('BLENDER_RIGHT', 'Blender Right (+Y)', ''),
        ],
        name='Up (+Y) to',
        description=(
            "Choose whether to convert coordinates to Blender's up-axis convention "
            'or leave everything in the same order it is in the glTF'
        ),
        default='BLENDER_UP',
    )
    smooth_polys = BoolProperty(
        name='Enable Polygon Smoothing',
        description=(
            'Enable smoothing for all polygons in imported meshes. Suggest '
            'disabling for low-res models'
        ),
        default=True,
    )
    split_meshes = BoolProperty(
        name='Split Meshes into Primitives',
        description=(
            'A glTF mesh is made of pieces called primitives. For example, each primitive '
            'uses only one material. When this option is disabled, one glTF mesh makes '
            'one Blender mesh. When it is enabled, each glTF primitive makes one Blender mesh. '
            'Useful for examining the structure of glTF meshes'
        ),
        default=False,
    )
    bone_rotation_mode = EnumProperty(
        items=[
            ('NONE', "Don't change", ''),
            ('POINT_TO_CHILDREN', 'Point to children', ''),
        ],
        name='Direction',
        description=(
            'Adjusts which direction bones will point towards by applying a rotation '
            'to each bone. Point-to-children uses a heuristic that tries to make bones '
            'point nicely'
        ),
        default='POINT_TO_CHILDREN',
    )
    import_animations = BoolProperty(
        name='Import Animations',
        description=(
            'Whether to import animations. Look for them in the Action Editor. '
            'One glTF animation is split up into multiple actions, depending on '
            'which object it targets and whether it targets TRS/material/shape key '
            'properties'
        ),
        default=True,
    )
    framerate = FloatProperty(
        name='Frames/second',
        description=(
            'The Blender animation frame corresponding to the glTF time is computed '
            "as framerate * t. Negative values or zero mean to use the current scene's "
            'framerate'
        ),
        default=0.0,
    )
    always_doublesided = BoolProperty(
        name='Always Double-Sided',
        description=(
            'Make all materials double-sided, even if the glTF says they should be '
            'single-sided.\n'
            'Single-sidedness (ie. backing culling enabled) is simulated in Blender '
            'using alpha, which is a somewhat ugly hack'
        ),
        default=True,
    )
    import_into_current_scene = BoolProperty(
        name='Import into Current Scene',
        description=(
            'When enabled, all the objects will be placed in the current '
            'scene and no scenes will be created.\n'
            'When disabled, scenes will be created to match the ones in the '
            'glTF file. Any object not in a scene will not be visible'
        ),
        default=True,
    )
    add_root = BoolProperty(
        name='Add Root Node',
        description=(
            'When enabled, everything in the glTF file will be placed under a new '
            'root node with the name of the .gltf/.glb file'
        ),
        default=True,
    )

    def draw(self, context):
        layout = self.layout

        col = layout.box().column()
        col.label(text='Units:', icon='EMPTY_DATA')
        col.prop(self, 'axis_conversion')
        col.prop(self, 'global_scale')

        col = layout.box().column()
        col.label(text='Mesh:', icon='MESH_DATA')
        col.prop(self, 'smooth_polys')
        col.prop(self, 'split_meshes')

        col = layout.box().column()
        col.label(text='Bones:', icon='BONE_DATA')
        col.prop(self, 'bone_rotation_mode')

        col = layout.box().column()
        col.label(text='Animation:', icon='POSE_HLT')
        col.prop(self, 'import_animations')
        col.prop(self, 'framerate')

        col = layout.box().column()
        col.label(text='Materials:', icon='MATERIAL_DATA')
        col.prop(self, 'always_doublesided')

        col = layout.box().column()
        col.label(text='Scene:', icon='SCENE_DATA')
        col.prop(self, 'import_into_current_scene')
        col.prop(self, 'add_root')

    def execute(self, context):
        imp = Importer(self.filepath, self.as_keywords())
        imp.do_import()
        return {'FINISHED'}


# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text="KSons' glTF 2.0 (.glb/.gltf)")


def register():
    if bpy.app.version >= (2, 80, 0):
        bpy.utils.register_class(ImportGLTF)
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    else:
        bpy.utils.register_module(__name__)
        bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    if bpy.app.version >= (2, 80, 0):
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        bpy.utils.unregister_class(ImportGLTF)
    else:
        bpy.utils.unregister_module(__name__)
        bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == '__main__':
    register()
