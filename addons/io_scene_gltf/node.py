import bpy
from mathutils import Matrix, Quaternion, Vector

"""
Handle nodes and scenes.

The glTF node forest is represented in Blender as a single armature, where the
nodes become bones. The meshes and cameras are set in the correct place in the
heirachy using a "Copy Transform" constraint to lock them to their parent. Using
an armature is necessary to skin meshes -- glTF skins through the configuration
of the node forest and Blender only skins through armatures (AFAIK). The main
drawback of this is that I don't think you can scale a bone's rest position so
scaling nodes doesn't work. Also, the bone positions are fairly meaningless.

COLLADA should have these problems too; check what it does? (I know it doesn't
solve the bone positions issue.)

For our purposes it would be really nice if Blender had an armature based on
joints instead of bones.

It would also be desirable to check that what we do gives the correst result ie.
the transform Blender does equals the one glTF calls for, but neither Blender
nor glTF have docs for exactly what that transform should be :-/

Scenes are represented by Blender scene. Each one has the whole node armature
linked in, but only has those meshes and cameras linked in that are "visible" in
that scene (ie. are descendants of one of the roots of the scene).
"""


def convert_matrix(m):
    """Converts a glTF matrix to a Blender matrix."""
    result = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    result.transpose()  # column-major to row-major
    return result


def convert_quaternion(q):
    """Converts a glTF quaternion to Blender a quaternion."""
    # xyzw -> wxyz
    return Quaternion([q[3], q[0], q[1], q[2]])


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


def create_objects(op, idx, root_idx):
    node = op.gltf['nodes'][idx]
    name = node.get('name', 'nodes[%d]' % idx)

    def create(name, data):
        ob = bpy.data.objects.new(name, data)
        ob.parent = op.armature_ob

        # TODO: make the object a child of the bone instead? Making it a
        # child puts it at the tail of the bone and we want it at the
        # head. We'd just need to translate it along the length of the
        # bone.
        con = ob.constraints.new('COPY_TRANSFORMS')
        con.target = op.armature_ob
        con.subtarget = op.node_to_bone_name[idx]

        ob.parent = op.armature_ob

        op.root_to_objects[root_idx].append(ob)

        return ob

    if 'mesh' in node:
        mesh_name = name
        if 'camera' in node:
            mesh_name += '.mesh'
        ob = create(mesh_name, op.get_mesh(node['mesh']))

        if 'skin' in node:
            skin = op.gltf['skins'][node['skin']]
            joints = skin['joints']
            for joint in joints:
                ob.vertex_groups.new(op.node_to_bone_name[joint])

            mod = ob.modifiers.new('rig', 'ARMATURE')
            mod.object = op.armature_ob
            mod.use_vertex_groups = True

    if 'camera' in node:
        camera_name = name
        if 'mesh' in node:
            camera_name += '.camera'
        create(camera_name, op.get_camera(node['camera']))

    for idx in node.get('children', []):
        create_objects(op, idx, root_idx)


def find_root_idxs(op):
    nodes = op.gltf.get('nodes', [])
    idxs = set(range(0, len(nodes)))
    for node in nodes:
        for child_idx in node.get('children', []):
            idxs.remove(child_idx)
    root_idxs = list(idxs)
    root_idxs.sort()
    op.root_idxs = root_idxs

    for root_idx in root_idxs:
        op.root_to_objects[root_idx] = []


def generate_armature_object(op):
    bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
    arma_ob = bpy.context.object
    arma_ob.name = 'Node Forest'
    arma_ob.show_x_ray = True
    arma = arma_ob.data
    arma.name = 'Node Forest'
    op.armature_ob = arma_ob

    # Turn glTF up (+Y) into Blender up (+Z)
    # TODO is this right?
    arma_ob.matrix_local = Matrix([
        [1, 0, 0, 0],
        [0, 0, -1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]
    ])

    def add_bone(idx, parent, parent_mat):
        node = op.gltf['nodes'][idx]
        name = node.get('name', 'node[%d]' % idx)
        # Urg, isn't this backwards from get_transform? Figure out why.
        mat = parent_mat * get_transform(node)

        bone = arma.edit_bones.new(name)
        bone.use_connect = False
        if parent:
            bone.parent = parent
        bone.head = mat * Vector((0, 0, 0))
        bone.tail = mat * Vector((0, 1, 0))
        bone.align_roll(mat * Vector((0, 0, 1)) - bone.head)
        # NOTE: bones don't seem to have non-uniform scaling.
        # This appears to be a serious problem for us.

        op.node_to_bone_name[idx] = bone.name

        children = node.get('children', [])
        for child_idx in children:
            add_bone(child_idx, bone, mat)

    for root_idx in op.root_idxs:
        add_bone(root_idx, None, Matrix())
    # Done with bones; node_to_bone_name is filled out.
    # Now create objects.
    for root_idx in op.root_idxs:
        create_objects(op, root_idx, root_idx)

    bpy.ops.object.mode_set(mode='OBJECT')

    # Linking it in, AFAICT, was necessary to enter edit mode for the above. But
    # create_scene is going to be responsible for linking it into each scene,
    # and linking it where it's already linked throws an error, so we unlink it
    # here for now.
    bpy.context.scene.objects.unlink(arma_ob)


def create_scene(op, idx):
    scene = op.gltf['scenes'][idx]
    name = scene.get('name', 'scene[%d]' % idx)

    bpy.ops.scene.new(type='NEW')
    scn = bpy.context.scene
    scn.name = name
    scn.render.engine = 'CYCLES'
    # scn.world.use_nodes = True

    # Always link in the whole node forest
    scn.objects.link(op.armature_ob)

    roots = scene.get('nodes', [])
    for root_idx in roots:
        # Link in any objects in this tree
        for ob in op.root_to_objects[root_idx]:
            scn.objects.link(ob)

    return scn


def generate_scenes(op):
    find_root_idxs(op)
    generate_armature_object(op)

    scenes = op.gltf.get('scenes', [])
    for scene_idx in range(0, len(scenes)):
        op.scenes[scene_idx] = create_scene(op, scene_idx)
