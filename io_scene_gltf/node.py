import bpy
import math
from mathutils import Matrix, Quaternion, Vector

def convert_matrix(m):
    """Convert glTF matrix to Blender matrix"""
    result = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    result.transpose() # column-major to row-major
    return result


def convert_quaternion(q):
    """Convert glTF quaternion to Blender quaternion"""
    return Quaternion([q[3], q[0], q[1], q[2]]) # xyzw -> wxyz


def get_transform(node):
    if 'matrix' in node:
        return convert_matrix(node['matrix'])
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
        return mat


def create_object(op, idx, scene, armature_ob, node_to_bone_map):
    node = op.root['nodes'][idx]
    name = node.get('name', 'nodes[%d]' % idx)

    def create(name, data):
        ob = bpy.data.objects.new(name, data)
        ob.parent = armature_ob

        con = ob.constraints.new('COPY_TRANSFORMS')
        con.target = armature_ob
        con.subtarget = node_to_bone_map[idx]

        ob.parent = armature_ob

        scene.objects.link(ob)

        return ob

    if 'mesh' in node:
        mesh_name = name
        if 'camera' in node:
            mesh_name += '.mesh'
        create(mesh_name, op.get_mesh(node['mesh']))

    if 'camera' in node:
        camera_name = name
        if 'mesh' in node:
            camera_name += '.camera'
        create(camera_name, op.get_camera(node['camera']))

    for idx in node.get('children', []):
        create_object(op, idx, scene, armature_ob, node_to_bone_map)


def create_tree(op, root_idx, scene):
    root_node = op.root['nodes'][root_idx]
    name = root_node.get('name', 'node[%d]' % root_idx)

    bpy.ops.object.add(
        type='ARMATURE',
        enter_editmode=True,
        location=(0,0,0))
    ob = bpy.context.object
    ob.name = name
    ob.show_x_ray = True
    amt = ob.data
    amt.name = name + '.AMT'

    node_to_bone_map = {}

    bpy.ops.object.mode_set(mode='EDIT')

    def add_bone(idx, parent, parent_mat):
        node = op.root['nodes'][idx]
        name = node.get('name', 'node[%d]' % idx)
        # Urg, isn't this backwards from get_transform? Figure out why.
        mat = parent_mat * get_transform(node)

        bone = amt.edit_bones.new(name)
        bone.use_connect = False
        if parent:
            bone.parent = parent
        bone.head = mat * Vector((0,0,0))
        #TODO use heuristic for bone length
        bone.tail = mat * Vector((0,0.2,0))
        bone.align_roll(mat * Vector((0,0,1)) - bone.head)
        #NOTE bones don't seem to have non-uniform scaling.
        # Maybe we can do something with the bind pose...

        node_to_bone_map[idx] = bone.name

        for child_idx in node.get('children', []):
            add_bone(child_idx, bone, mat)

    add_bone(root_idx, None, Matrix())

    bpy.ops.object.mode_set(mode='OBJECT')

    create_object(op, root_idx, scene, ob, node_to_bone_map)

    return ob


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
        create_tree(op, root_idx, scn)

    scn.update()

    op.scenes[idx] = scn
