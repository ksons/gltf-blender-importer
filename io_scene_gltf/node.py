import bpy
from mathutils import Matrix
from mathutils import Quaternion
from mathutils import Vector


def convert_matrix(m):
    """Convert glTF matrix to Blender matrix"""
    result = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    result.transpose() # column-major to row-major
    return result


def convert_quaternion(q):
    """Convert glTF quaternion to Blender quaternion"""
    return Quaternion([q[3], q[0], q[1], q[2]]) # xyzw -> wxyz


def set_transform(obj, node):
    if 'matrix' in node:
        obj.matrix_local = convert_matrix(node['matrix'])
    else:
        mat = Matrix()
        if 'scale' in node:
            s = node['scale']
            mat = Matrix([
                [s[0], 0, 0, 0],
                [0, s[1], 0, 0],
                [0, 0, s[2], 0],
                [0, 0, 0, 1]
            ])
        if 'rotation' in node:
            q = convert_quaternion(node['rotation'])
            mat = q.to_matrix().to_4x4() * mat
        if 'translation' in node:
            t = Vector(node['translation'])
            mat = Matrix.Translation(t) * mat
        obj.matrix_local = mat


def create_object(op, idx, parent, scene):
    node = op.root['nodes'][idx]
    name = node.get('name', 'nodes[%d]' % idx)
    ob = bpy.data.objects.new(name, None)

    if 'mesh' in node:
        mesh_ob = bpy.data.objects.new(
            name + '.mesh',
            op.get_mesh(node['mesh'])
        )
        mesh_ob.parent = ob
        scene.objects.link(mesh_ob)
    if 'camera' in node:
        camera_ob = bpy.data.objects.new(
            name + '.camera',
            op.get_camera(node['camera'])
        )
        camera_ob.parent = ob
        scene.objects.link(camera_ob)

    set_transform(ob, node)

    ob.parent = parent
    bpy.context.scene.objects.link(ob)
    scene.update()

    if 'children' in node:
        children = node['children']
        for idx in children:
            create_object(op, idx, ob, scene)


def create_scene(op, idx):
    scene = op.root['scenes'][idx]
    name = scene.get('name', 'scene[%d]' % idx)

    bpy.ops.scene.new(type='NEW')
    scn = bpy.context.scene
    scn.name = name
    scn.render.engine = 'CYCLES'
    #scn.world.use_nodes = True

    roots = scene.get('nodes', [])
    for root_idx in roots:
        create_object(op, root_idx, None, scn)

    scn.update()

    op.scenes[idx] = scn
