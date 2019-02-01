from mathutils import Vector, Quaternion
from . import buffer, mesh, camera, light, material, animation, load, vnode, node, scene

class Importer:
    """Manages all import state."""

    def __init__(self, filepath, options):
        self.filepath = filepath
        self.options = options
        self.caches = {}

    def do_import(self):
        self.set_conversions()

        load.load(self)

        # Precomputations
        material.material_precomputation(self)
        if self.options['import_animations']:
            animation.gather_animation_info(self)

        vnode.create_vtree(self)
        node.realize_vtree(self)
        scene.create_blender_scenes(self)
        if self.options['import_animations']:
            animation.add_animations(self)

    def get(self, kind, id):
        """
        Gets some kind of resource, eg. a decoded accessor, a mesh, etc. Kept in
        a cache to enable sharing.
        """
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

    def set_conversions(self):
        """
        Set the convert_{translation,rotation,scale} functions for converting
        from glTF to Blender units. The user can configure this.
        """
        global_scale = self.options['global_scale']
        axis_conversion = self.options['axis_conversion']

        if axis_conversion == 'BLENDER_UP':
            def convert_translation(t):
                return global_scale * Vector([t[0], -t[2], t[1]])

            def convert_rotation(r):
                return Quaternion([r[3], r[0], -r[2], r[1]])

            def convert_scale(s):
                return Vector([s[0], s[2], s[1]])

        else:
            def convert_translation(t):
                return global_scale * Vector(t)

            def convert_rotation(r):
                return Quaternion([r[3], r[0], r[1], r[2]])

            def convert_scale(s):
                return Vector(s)

        self.convert_translation = convert_translation
        self.convert_rotation = convert_rotation
        self.convert_scale = convert_scale
