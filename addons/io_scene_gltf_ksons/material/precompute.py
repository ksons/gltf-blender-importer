from ..mesh import MAX_NUM_COLOR_SETS

class MaterialInfo:
    def __init__(self):
        # The maximum number of color sets used by any primitive with this
        # material, ie. the smallest n st. no primitive with this material has a
        # COLOR_n attribute.
        self.num_color_sets = 0
        # The set of "live" material property names that have to correspond to
        # some value in the Blender shader tree, because we're going to want to
        # animate them.
        self.liveness = set()
        # Maps a property name to its Blender path suitable for animation. All
        # live properties must get an entry here.
        self.paths = {}

def material_procomputation(op):
    op.material_infos = {
        idx: MaterialInfo()
        for idx, __material in enumerate(op.gltf.get('materials', []))
    }
    op.material_infos['default_material'] = MaterialInfo()

    # Find out what vertex colors materials use
    for mesh in op.gltf.get('meshes', []):
        for primitive in mesh['primitives']:
            i = 0
            while 'COLOR_%d' % i in primitive['attributes']:
                if i >= MAX_NUM_COLOR_SETS:
                    break

                mat = primitive.get('material', 'default_material')
                if i >= op.material_infos[mat].num_color_sets:
                    op.material_infos[mat].num_color_sets = i + 1
                i += 1
