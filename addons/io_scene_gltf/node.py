import bpy
from mathutils import Matrix, Quaternion, Vector

def set_transform(node, ob):
    if 'matrix' in node:
        m = node['matrix']
         # column-major to row-major
        m = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        m.transpose()
        (loc, rot, sca) = m.decompose()
    else:
        sca = node.get('scale', [1.0, 1.0, 1.0])
        rot = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
        rot = [rot[3], rot[0], rot[1], rot[2]] # xyzw -> wxyz
        loc = node.get('translation', [0.0, 0.0, 0.0])

    # Switch glTF coordinates to Blender coordinates
    sca = [sca[0], sca[2], sca[1]]
    rot = [rot[0], rot[1], -rot[3], rot[2]]
    loc = [loc[0], -loc[2], loc[1]]

    ob.location = loc
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = rot
    ob.scale = sca


def create_node(op, idx):
    node = op.gltf['nodes'][idx]
    name = node.get('name', 'nodes[%d]' % idx)

    if 'mesh' in node and 'camera' in node:
        # Blender objects can't have >1 data item (I think?) so create some
        # dummy children to hold them
        ob = bpy.data.objects.new(name, None)
        mesh_ob = bpy.data.objects.new(
            name + '.mesh',
            op.get_mesh(node['mesh'])
        )
        camera_ob = bpy.data.objects.new(
            name + '.camera',
            op.get_camera(node['camera'])
        )
        mesh_ob.parent = ob
        camera_ob.parent = ob
    elif 'mesh' in node:
        ob = bpy.data.objects.new(name, op.get_mesh(node['mesh']))
    elif 'camera' in node:
        ob = bpy.data.objects.new(name, op.get_camera(node['camera']))
    else:
        ob = bpy.data.objects.new(name, None)

    set_transform(node, ob)

    for child_idx in node.get('children', []):
        op.get_node(child_idx).parent = ob

    return ob


def create_scene(op, idx):
    scene = op.gltf['scenes'][idx]
    name = scene.get('name', 'scene[%d]' % idx)
    scn = bpy.data.scenes.new(name)
    scn.render.engine = 'CYCLES'

    roots = scene.get('nodes', [])
    for root_idx in roots:
        def link_hierarchy(root):
            scn.objects.link(root)
            for child in root.children:
                link_hierarchy(child)
        link_hierarchy(op.get_node(root_idx))

    return scn
