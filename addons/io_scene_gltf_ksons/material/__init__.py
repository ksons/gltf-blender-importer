from . import image, material, node_groups

create_material = material.create_material
create_image = image.create_image
create_group = node_groups.create_group


def compute_materials_using_color0(op):
    """Compute which materials use vertex color COLOR_0.

    I don't know how to have a material be influenced by vertex colors when a
    mesh has them and not be when they aren't. If you slot in an attribute node
    it will emit solid red when the attribute layer is missing (if it produced
    solid white everything would be fine) and, of course, if you don't the
    attribute won't influence the material.

    Hence this work-around: we compute for each material whether it is ever used
    in a primitive that uses vertex colors and mark it down. For these materials
    only we slot in an attribute node for vertex colors. In mesh.py we also need
    to make sure that any mesh that uses one of these materials has a COLOR_0
    attribute.
    """
    op.materials_using_color0 = set()
    for mesh in op.gltf.get('meshes', []):
        for primitive in mesh['primitives']:
            if 'COLOR_0' in primitive['attributes']:
                mat = primitive.get('material', 'default_material')
                op.materials_using_color0.add(mat)
