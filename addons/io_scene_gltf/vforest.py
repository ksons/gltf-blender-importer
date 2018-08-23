from math import pi
from mathutils import Matrix, Quaternion, Vector, Euler

# This file build a "virtual forest" (vforest) of "virtual nodes" (vnodes) that
# mirror how we'll create a Blender scene graph for glTF. We modify it
# extensively as we build it which is hard to do with the real Blender scene,
# which is why we first build it "virtually" like this.

def create_vforest(op):
    init(op)
    insert_armatures(op)
    adjust_bones(op)
    adjust_instances(op)


# In the first pass we create a vforest that exactly mirrors the forest in the
# glTF file:
#
#       o1
#      /  \
#     o2   o3
#         /  \
#        o4   o5
#
# If no vnode had more than one instance on it, we could import this into
# Blender creating objects for each vnode (an empty if the vnode had no
# instance), setting parents and TRS properties appropiately, and have a perfect
# copy of the forest from the glTF.
def init(op):
    nodes = op.gltf.get('nodes', [])

    op.vnodes = []
    op.id_to_vnode = {}

    # Initial pass: create a vnode for each node
    for id, node in enumerate(nodes):
        vnode = {
            'node_id': id,
            'name': node.get('name', 'nodes[%d]' % id),
            'parent': None,
            'children': [],
            'type': 'NORMAL',
            'trs': get_trs(node),
        }
        if 'mesh' in node:
            vnode['mesh_instance'] = {
                'mesh': node['mesh'],
                'skin': node.get('skin'),
                'weights': node.get('weights', op.gltf['meshes'][node['mesh']].get('weights')),
            }
        if 'camera' in node:
            vnode['camera_instance'] = {
                'camera': node['camera'],
            }

        op.id_to_vnode[id] = vnode
        op.vnodes.append(vnode)

    # Fill in the parent/child relationships
    for id, node in enumerate(nodes):
        vnode = op.id_to_vnode[id]
        for child_id in node.get('children', []):
            child_vnode = op.id_to_vnode[child_id]
            child_vnode['parent'] = vnode
            vnode['children'].append(child_vnode)


# Alas, in order to do skinning, we must break this perfect representation by
# inserting armatures. In this stage we insert "enough armatures" so that every
# vnode which is the joint of a skin is a descendant of an armature. All those
# vnodes which are the descendants of an armature will be realized in Blender as
# bones.
#
#       o1
#      /  \
#     o2  arma
#          |
#          b3
#         /  \
#        b4   b5
#
# Note that an armature may join together two trees that were originally
# seperate if a skin has joints in multiple trees.
#
# It's not very important exactly how we insert "enough armatures". One way
# would be to insert a single armature at the root, but as we shall see bones
# have certain deficiencies that make it desirable that as few vnodes as
# possible be bones. Currently we insert armatures for each skin at that skin's
# declared skeleton root, or at the lowest possible point if none is declared.
def insert_armatures(op):
    def insert_parent(vnodes, parent):
        # If there is one vnode, inserts parent between it and its parent.
        # Otherwise, vnodes must all be roots and inserts parent as their
        # common parent.
        for vnode in vnodes:
            old_parent = vnode['parent']
            vnode['parent'] = parent
            parent['children'].append(vnode)
            if old_parent:
                assert(len(vnodes) == 1)
                pos = old_parent['children'].index(vnode)
                old_parent['children'][pos] = parent
                parent['parent'] = old_parent
            else:
                parent['parent'] = None

    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):
        if 'skeleton' not in skin:
            joint_vnodes = [op.id_to_vnode[joint_id] for joint_id in skin['joints']]
            skeleton_roots = lowest_common_ancestors(joint_vnodes)
        else:
            # TODO: not sure the spec actually guarantees that the
            # skin['skeleton'] node will be an (improper) ancestor of the
            # joints... could always use the other branch...
            skeleton_roots = [op.id_to_vnode[skin['skeleton']]]

        armature = {
            'name': skin.get('name', 'skins[%d]' % skin_id),
            'children': [],
            'type': 'ARMATURE',
            'parent': None,
        }
        op.vnodes.append(armature)
        insert_parent(skeleton_roots, armature)

    # Mark all the children of armatures as bones and delete any armatures that
    # are the descendants of other armatures.

    def delete_vnode(vnode):
        if vnode['parent']:
            children = vnode['parent']['children']
            del children[children.index(vnode)]
            children += vnode['children']
        for child in vnode['children']:
            child['parent'] = vnode['parent']
        del op.vnodes[op.vnodes.index(vnode)]

    def visit(vnode, armature_vnode):
        if armature_vnode:
            if vnode['type'] == 'ARMATURE':
                armature_vnode['name'] += '&' + vnode['name']
                delete_vnode(vnode)
            else:
                vnode['armature_vnode'] = armature_vnode
                vnode['type'] = 'BONE'
        else:
            if vnode['type'] == 'ARMATURE':
                armature_vnode = vnode

        for child in vnode['children']:
            visit(child, armature_vnode)

    # Root node are now fixed so compute them
    op.root_vnodes = [vnode for vnode in op.vnodes if not vnode['parent']]

    for root_vnode in op.root_vnodes:
        visit(root_vnode, None)

    # Armature nodes are now fixed so compute them too
    op.armature_vnodes = [vnode for vnode in op.vnodes if vnode['type'] == 'ARMATURE']


# A bone has two "parts": the edit bone, which is what is specified in edit
# mode, and the pose bone, which is what is specified in pose mode. The
# local-to-parent transform for the bone is determined by
#
#     (blender TRS) = (edit bone transform) * (pose bone transform)
#
# We would like the edit bone transform to be the TRS transform just like in the
# original perfect forest but there are two reasons we don't have this. The more
# serious one is that an edit bone cannot have a scale (we'll return to this).
# The less serious one is that we may want to rotate a bone so it points the
# "right way". In Blender, bones point along their local Y-axis. We can change
# the local Y-axis by using
#
#     (blender TRS) = (post-rotation) (true TRS) (pre-rotation)          (*)
#
# where post-rotation is chosen to cancel out the pre-rotation on the bone's
# parent so that composing them up the tree you get as the total local-to-world
# transform
#
#     (blender local-to-world) = (true local-to-world) (pre-rotation)
#
# Then when a camera or an unskinned mesh is a child of a bone, we can add a
# local correction of (pre-rotation)^{-1} to get it to have the correct
# world-space position.
#
# For skinned meshes, since vertices are skinned by a linear combination of
# terms of the form
#
#     (blender posed local-to-arma) (blender rest local-to-arma)^{-1} =
#     (true posed local-to-arma) (pre-rot) (pre-rot^{-1}) (true rest local-to-arma)^{-1} =
#     (true posed local-to-arma) (true rest local-to-arma)^{-1}
#
# this pre-rotation doesn't affect them at all.
#
# What about scalings? AFAICT we are obliged to put them on the pose bones. So
# if we have
#
#     (edit bone TR) = (post-rotation) (true TR) (pre-rotation)
#     (blender TRS) = (post-rotation) (true TR) (pre-rotation) (pose scale)
#
# we need to interchange the order of the pre-rotation and scale to get (*) to
# hold. In general this is impossible, but if the rotation is (up to signs) a
# permutation of the basis vectors (eg. X,Y,Z -> X,Z,-Y) we can interchange them
# by
#
#     Rot[r] Scale[s'] = Scale[s] Rot[r]
#       where s'_k = s_{p(k)}
#       where p is the permutation st. Rot[r] e_k = e_{p(k)} (ignoring signs)
#
# So we;ve found our pre-rotations have to have a special form.
#
# Adding in this scale makes our bones have the correct position in pose mode so
# it works for unskinned meshes and cameras which are only affected by the
# current pose. But skinned meshes are also affected by the edit pose and the
# edit pose is wrong if (true TRS) has non-unit scalings. This seems hard to fix
# (the case where the scalings are at least uniform seems a bit easier). We
# currently warn if a rest scaling is not 1 and just pretend that it was.
def adjust_bones(op):
    # In the first pass, compute the true_TRS without any pre-rotation, etc. The
    # pre-rotations don't affect the bone heads (ie. the image of the origin
    # under the local-to-arma transform) so we can compute them now.
    def visit1(vnode):
        t, r, s = vnode['trs']

        # Mark this so we can print a warning later
        if any(abs(s[i] - 1) > 0.05 for i in range(0, 3)):
            vnode['bone_had_nonunit_scale'] = True

        vnode['bone_tr'] = [t, r]

        # Blender specifies bones in a weird way; you don't give their
        # local-to-parent transform like for regular objects, you basically give
        # their armature space positions. So we start by computing their
        # local-to-arma matrix.
        mat = vnode['parent'].get('bone_mat', Matrix.Identity(4))
        mat = mat * Matrix.Translation(t) * r.to_matrix().to_4x4()
        vnode['bone_mat'] = mat

        vnode['bone_head'] = mat * Vector((0, 0, 0))

        for child in vnode['children']:
            visit1(child)

    for arma_vnode in op.armature_vnodes:
        for child in arma_vnode['children']:
            visit1(child)

    # The second pass pass computes a length for each bone, ideally the distance
    # from its head to its (first) child. Bone lengths don't affect the bone's
    # TRS transform.
    def compute_lengths(vnode):
        bone_length = 1
        if 'bone_length' in vnode['parent']:
            bone_length = vnode['parent']['bone_length']
        for child in vnode['children']:
            if child['type'] == 'BONE':
                dist = (vnode['bone_head'] - child['bone_head']).length
                if dist != 0:
                    bone_length = dist
                    break
        vnode['bone_length'] = bone_length # record it for our children

        for child in vnode['children']:
            compute_lengths(child)

    for arma_vnode in op.armature_vnodes:
        for child in arma_vnode['children']:
            compute_lengths(child)

    # Figure out what pre-rotation to use
    if op.bone_rotation == 'NONE':
        axis = '+Y'
    elif op.bone_rotation == 'GUESS':
        axis = guess_bone_axis(op)
    elif op.bone_rotation == 'MANUAL':
        axis = op.bone_rotation_axis
    else:
        assert(False)
    euler = {
        '-X': Euler([0, 0, pi/2]),
        '+X': Euler([0, 0, -pi/2]),
        '-Y': Euler([pi, 0, 0]),
        '+Y': Euler([0, 0, 0]),
        '-Z': Euler([-pi/2, 0, 0]),
        '+Z': Euler([pi/2, 0, 0]),
    }[axis]
    pre_rotate = euler.to_quaternion()
    pre_rotate_mat = euler.to_matrix().to_4x4()

    # The permuation that the pre-rotation does to the basis vectors
    pre_perm = {
        '-X': [1, 0, 2],
        '+X': [1, 0, 2],
        '-Y': [0, 1, 2],
        '+Y': [0, 1, 2],
        '-Z': [0, 2, 1],
        '+Z': [0, 2, 1],
    }[axis]

    # In the third and final pass, we use the pre-rotations to find the bone
    # tails and update the bone TR.
    def visit3(vnode):
        t, r, s = vnode['trs']
        if 'bone_post_rotate' in vnode:
            post_rotate = vnode['bone_post_rotate']
            t = post_rotate.to_matrix() * t
            r = post_rotate * r
        vnode['bone_pre_rotate'] = pre_rotate
        vnode['bone_pre_perm'] = pre_perm
        r = r * pre_rotate
        for child in vnode['children']:
            child['bone_post_rotate'] = pre_rotate.conjugated()

        # Compute s'
        vnode['bone_pose_s'] = Vector((s[pre_perm[0]], s[pre_perm[1]], s[pre_perm[2]]))

        vnode['bone_mat'] *= pre_rotate_mat
        vnode['bone_tr'] = t, r

        vnode['bone_tail'] = vnode['bone_mat'] * Vector((0, vnode['bone_length'], 0))
        vnode['bone_align'] = vnode['bone_mat'] * Vector((0, 0, 1)) - vnode['bone_head']

        for child in vnode['children']:
            visit3(child)

    for arma_vnode in op.armature_vnodes:
        for child in arma_vnode['children']:
            visit3(child)

def guess_bone_axis(op):
    # This function guesses which local axis bones should point along in this
    # way: all the bones that have one child cast a vote for whichever axis (if
    # any) points from their head to their child's head. If any axis gets a
    # majority vote, that's the axis we use. Otherwise, we use the default +Y
    # axis.
    votes = {}
    voters = [0]
    axes = {
        '-X': Vector((-1,  0,  0)),
        '+X': Vector(( 1,  0,  0)),
        '-Y': Vector(( 0, -1,  0)),
        '-Z': Vector(( 0,  0, -1)),
        '+Z': Vector(( 0,  0,  1)),
    }
    def visit2(vnode):
        if len(vnode['children']) == 1:
            child = vnode['children'][0]
            dist = (child['bone_head'] - vnode['bone_head']).length
            if dist >= 0.005: # only if the heads are not incident
                voters[0] += 1
                for key, axis in axes.items():
                    tail = vnode['bone_mat'] * (dist * axis)
                    if (tail - child['bone_head']).length < 0.1 * dist:
                        votes.setdefault(key, 0)
                        votes[key] += 1
                        break

        for child in vnode['children']:
            visit2(child)

    for arma_vnode in op.armature_vnodes:
        for child in arma_vnode['children']:
            visit2(child)

    for key, vote_count in votes.items():
        if vote_count > voters[0] // 2:
            print('Guessing bones should point along', key, '...')
            return key

    # No majority; don't use a rotation
    return '+Y'


# A Blender object can contain only one datum (eg. a mesh, a camera, etc.) and a
# Blender bone cannot contain one at all, so we have to move some of these
# instances onto child nodes, eg. if o2 had a mesh and a camera and b5 had a
# mesh
#
#           o1
#          /  \
#         o2  arma
#       /  |   |
#      / mesh  b3
#   camera    /  \
#            b4   b5
#                  |
#                mesh
#
# Note that after this step, a decendent of an armature vnode no longer need be
# a bone.
def adjust_instances(op):
    def move_to_child(vnode, inst_kind):
        inst = vnode[inst_kind]
        del vnode[inst_kind]

        if vnode['type'] == 'BONE':
            # For bones, Blender puts a child at the tail, not the head (whyyy).
            # So we need to translate backwards along the bone's vector (= local
            # Y-axis).
            #
            # We also need to rotate to correct for the pre-rotation on the
            # bone. See above.
            t = Vector((0, -vnode['bone_length'], 0))
            r = vnode.get('bone_pre_rotate', Quaternion((1, 0, 0, 0))).conjugated()
        else:
            t = Vector((0, 0, 0))
            r = Quaternion((1, 0, 0, 0))
        s = Vector((1, 1, 1))

        if inst_kind == 'mesh_instance':
            id = inst['mesh']
            name = op.gltf['meshes'][id].get('name', 'meshes[%d]' % id)
        elif inst_kind == 'camera_instance':
            id = inst['camera']
            name = op.gltf['cameras'][id].get('name', 'cameras[%d]' % id)
            # Add a quater-turn around the X-axis to account for the fact that
            # Blender cameras look along the -Z axis, while glTF ones look along
            # the -Y axis (in Blender coordinates)
            x_rot = Quaternion((2**(1/2), 2**(1/2), 0, 0))
            r *= x_rot
        else:
            assert(False)

        new_vnode = {
            'name': name,
            'parent': vnode,
            'children': [],
            'type': 'NORMAL',
            'trs': (t, r, s),
            'moved': True, # So we know we've already done this vnode
            inst_kind: inst,
        }
        op.vnodes.append(new_vnode)
        vnode['children'].append(new_vnode)
        vnode[inst_kind + '_moved_to'] = new_vnode
        return new_vnode


    for vnode in op.vnodes:
        if vnode.get('moved', False):
            continue

        if 'camera_instance' in vnode:
            move_to_child(vnode, 'camera_instance')

        if 'mesh_instance' in vnode:
            if vnode['type'] == 'BONE':
                move_to_child(vnode, 'mesh_instance')




def get_trs(node):
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

    return (Vector(loc), Quaternion(rot), Vector(sca))


def lowest_common_ancestors(vnodes):
    """
    Compute the lowest common ancestors of vnodes, if they are all in the same
    tree, or the list of roots of the trees which contain them, if they are not.
    """
    assert(vnodes)

    def ancestors(vnode):
        # Returns the chain of all ancestors of a vnode. The roots of the tree it
        # is in the first element and vnode itself is the last.
        chain = []
        while vnode:
            chain.append(vnode)
            vnode = vnode['parent']
        chain.reverse()
        return chain

    def first_difference(chain1, chain2):
        # Returns the index of the first difference in two chains, or None if
        # one is a prefix of the other.
        i = 0
        while True:
            if i == len(chain1) or i == len(chain2):
                return None
            if chain1[i] != chain2[i]:
                return i
            i += 1

    # Used when the vnodes belong to multiple trees; list of roots of all the
    # trees
    multiple = []
    # Used when they belong to the same tree; ancestor chain for the current
    # lowest common ancestor
    lowest = ancestors(vnodes[0])

    for vnode in vnodes[1:]:
        current = ancestors(vnode)
        if multiple:
            if current[0] not in multiple:
                multiple.append(current[0])
        else:
            d = first_difference(lowest, current)
            if d is None:
                if len(current) < len(lowest):
                    lowest = current
            elif d == 0:
                # Their roots differ: switch to multiple mode
                multiple += [lowest[0], current[0]]
            else:
                lowest = lowest[:d]

    if multiple:
        return multiple
    else:
        return [lowest[-1]]
