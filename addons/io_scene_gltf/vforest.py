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
        if 'KHR_lights_punctual' in node.get('extensions', {}):
            vnode['light_instance'] = {
                'light': node['extensions']['KHR_lights_punctual']['light'],
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
        # Inserts parent as the parent of vnodes. All the vnodes must have the
        # same original parent (possibly None).
        first = True
        for vnode in vnodes:
            old_parent = vnode['parent']
            vnode['parent'] = parent
            parent['children'].append(vnode)
            parent['parent'] = old_parent
            if old_parent:
                pos = old_parent['children'].index(vnode)
                if first:
                    old_parent['children'][pos] = parent
                else:
                    del old_parent['children'][pos]
            first = False

    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):
        armature = {
            'name': skin.get('name', 'skins[%d]' % skin_id),
            'children': [],
            'type': 'ARMATURE',
            'parent': None,
        }
        op.vnodes.append(armature)

        # We're going to find a place to insert the armature.
        vnodes = [op.id_to_vnode[joint_id] for joint_id in skin['joints']]
        # The standard doesn't guarantee much about the 'skeleton' node. Throw
        # it into the pot! If it's really an ancestor of the joints, this will
        # make the armature be inserted at the skeleton.
        if 'skeleton' in skin:
            vnodes.append(op.id_to_vnode[skin['skeleton']])
        vnodes = lowest_common_ancestors(vnodes)

        # If there is one lowest common ancestor and it isn't a joint, we can
        # insert the armature below it instead of above it.
        if len(vnodes) == 1:
            if vnodes[0].get('node_id', -1) not in skin['joints']:
                vnodes = list(vnodes[0]['children'])

        insert_parent(vnodes, armature)

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

        for child in list(vnode['children']):
            visit(child, armature_vnode)

    # Root node are now fixed so compute them
    op.root_vnodes = [vnode for vnode in op.vnodes if not vnode['parent']]

    for root_vnode in op.root_vnodes:
        visit(root_vnode, None)

    # Armature nodes are now fixed so compute them too
    op.armature_vnodes = [vnode for vnode in op.vnodes if vnode['type'] == 'ARMATURE']


# Here's the complicated pass. We would have liked for the bones' TRS transforms
# to just be the nodes' TRS transforms, but this is not possible for two
# reasons. One, a Blender edit bone cannot have a scaling (or its scaling is
# always 1). And two, a bone always "points" along its local +Y-axis, and this
# is often not the direction we want it to point.
#
# So we need to retarget the bone heirarchy onto a new bind pose. Here's how you
# do it.
#
# A bone, b, has a local-to-parent transform that is the composition of a pose
# transform (from the pose bone) and an edit transform (from the edit bone)
#
#     T(b) = E(b) P(b)
#
# We want to change the edit bones (ie. the rest pose) to a new pose E'(b),
# which has unit scaling and is rotated to point some way we think is better,
# but where all the vertices end up at the same world space position. To do it,
# we choose per-bone coordinate changes C(b) = Cs(b) Cr(b) (that is, Cs(b) is a
# scaling, Cr(b) is a rotation) and replace
#
#     T'(b) = C(pb)^{-1} T(b) C(b)
#     or
#     E'(b) = C(pb)^{-1} E(b) C(b)
#     P'(b) = C(b)^{-1} P(b) C(b)
#
# where pb is the parent of bone b. Now the local-to-arma transform for b is the
# composition
#
#     L(b) = ... T(ppb) T(pb) T(b)
#
# so it changes to
#
#     L'(b) = ... T'(ppb) T'(pb) T'(b)
#           = ... C(pppb)^{-1} T(ppb) C(ppb) C(ppb)^{-1} T(pb) C(pb) C(pb)^{-1} T(b) C(b)
#            { all C(x)^{-1} C(x) factors cancel }
#           = ... T(ppb) T(pb) T(b) C(b)
#           = L(b) C(b)
#
# so the local-to-arma transforms are only affected by being premultipled by the
# change at b (ie. the change is only local).
#
# Similarly the inverse bind transforms, defined by
#
#     I(b) = (... E(ppb) E(pb) E(b))^{-1}
#          = E(b)^{-1} E(pb)^{-1} E(ppb)^{-1} ...
#
# change to
#
#     I'(b) = C(b)^{-1} I(b)
#
# As a result L'(b) I'(b) = L(b) I(b), so skinned vertices, which are computed
# from
#
#     \sum_b weight(b) L(b) I(b) position
#
# are unchanged in the new bind pose. Unskinned vertices at b, like for an
# unskinned mesh or a camera, can be put in the correct place by adding a local
# correction of C(b)^{-1} between them and b.
#
#     L'(b) C(b)^{-1} position = L(b) position
#
# So the net result is that the bind pose has changed, but all the world
# position are the same.
#
# There are two problems:
#
# First, that TRS transforms do not form a group, so an expression like
# C(pb)^{-1} E(b) C(b) is not necessarily a TRS transform (and so obviously we
# can't set the bone's transform to it). This comes down to the fact that there
# is not necessarily a solution r', s' to the equation
#
#     Scale[s] Rot[r] = Rot[r'] Scale[s']
#
# This is the more serious problem. It impacts our ability to make the world
# space positions accurate.
#
# Second, even if they did form a group, in the expression for P'(b), it is not
# necessarily the case that the translation component depends only on the
# translation of P(b) (plus the Cs), the rotation depends only on the rotation,
# etc. This failure means we would not be able to calculate animation curves
# independently. The scale curve could affect the rotation curve, so we would
# have to resample them onto a common domain, etc. This is undesirable (but it
# is possible, there's code for it in our git history somewhere) not only
# because it adds more complex code, but because the user loses the imformation
# about what the time domain in the glTF file looked like.
#
# We "solve" these two problems by making the following dicta:
#
# First, we always assume that
#
#     Cs(b) commutes with any rotation: Cs(b) Rot[r] = Rot[r] Cs(b).
#
# If the rest scalings are all homogenous, then the Cs(b) scalings are also
# homogenous and this assumption is justified. What if your model had
# non-homogenous rest scalings? Too bad, we assume it anyway! You're lucky we'll
# even look at your crummy model, ya dog. Maybe you'll get a warning. Anyway
# it's not clear to me that it's possible in general to retarget a bind pose
# that uses non-homogenous scalings onto one that doesn't use any scalings
# without some kind of loss of accuracy.
#
# Second, the Cr(b) rotations are picked to have a special form. They are, up to
# sign, a permutation of the basis vectors, eg. X,Y,Z -> X,Z,-Y. This also
# allows them to interchange with a scaling
#
#     Rot[Cr(b)] Scale[s'] = Scale[s] Rot[Cr(b)]
#       where s'_k = s_{p(k)}
#       where p is the permutation st. Rot[Cr(b)] e_k = e_{p(k)} (ignoring signs)
#
# This is necessary to get them to work with the scaling on the pose bones (in
# animation importing) which we have not restricted to being homogenous.
def adjust_bones(op):
    axes = {
        '-X': Vector((-1,  0,  0)),
        '+X': Vector(( 1,  0,  0)),
        '-Y': Vector(( 0, -1,  0)),
        '-Z': Vector(( 0,  0, -1)),
        '+Z': Vector(( 0,  0,  1)),
    }
    # Each of these carries the corresponding axis into the +Y axis. Used for
    # picking Cr(b).
    eulers = {
        '-X': Euler([0, 0, pi/2]),
        '+X': Euler([0, 0, -pi/2]),
        '-Y': Euler([pi, 0, 0]),
        '+Y': Euler([0, 0, 0]),
        '-Z': Euler([-pi/2, 0, 0]),
        '+Z': Euler([pi/2, 0, 0]),
    }
    # These are the underlying permutation of the basis vectors for the
    # transforms in eulers. Used to compute s' in animation.py.
    perms = {
        '-X': [1, 0, 2],
        '+X': [1, 0, 2],
        '-Y': [0, 1, 2],
        '+Y': [0, 1, 2],
        '-Z': [0, 2, 1],
        '+Z': [0, 2, 1],
    }
    # The list of distances between bone heads (used for computing bone lengths)
    interbone_dists = []

    def approx_neq(x, y): return abs(x-y) > 0.005
    op.bones_with_nonhomogenous_scales = []

    def visit(vnode):
        t, r, s = vnode['trs']

        # Record this so we can warn about it
        if approx_neq(s[0], s[1]) or approx_neq(s[1], s[2]) or approx_neq(s[0], s[2]):
            op.bones_with_nonhomogenous_scales.append(vnode)

        # Apply C(pb)^{-1} = Cr(pb)^{-1} Cs(pb)^{-1} = Rot[post_rotate] Scale[post_scale]
        post_rotation = vnode['parent'].get('bone_pre_rotation', Quaternion((1,0,0,0))).conjugated()
        post_scale = Vector((1/c for c in vnode['parent'].get('bone_pre_scale', [1,1,1])))
        # Rot[post_rotate] Scale[post_scale] Trans[t] Rot[r] Scale[s] =
        # Trans[Rot[post_rotate] Scale[post_scale] t] Rot[post_rotate * r] Scale[post_scale * s]
        t = post_rotation.to_matrix() * t
        t = Vector((post_scale[i] * t[i] for i in range(0, 3)))
        r = post_rotation * r
        s = Vector((post_scale[i] * s[i] for i in range(0, 3)))

        # Choose a pre-scaling that will cancel out our scaling, s.
        vnode['bone_pre_scale'] = Vector((1/sc for sc in s))

        # Choose a pre-rotation
        axis = None
        if op.bone_rotation_mode == 'MANUAL':
            axis = op.bone_rotation_axis
        elif op.bone_rotation_mode == 'AUTO':
            # We choose an axis that makes our tail close to the head of the
            # one of our children
            def guess_axis():
                for child in vnode['children']:
                    head = child['trs'][0]
                    head = Vector((head[i] * s[i] for i in range(0, 3)))
                    length = head.length
                    if length > 0.0005:
                        for axis_name, vec in axes.items():
                            if (vec * length - head).length < length * 0.25:
                                return axis_name
                return None

            axis = guess_axis()
            # Otherwise use the same axis our parent used
            if not axis:
                axis = vnode['parent'].get('bone_pre_rotation_axis', '+Y')
        elif op.bone_rotation_mode == 'NONE':
            axis = '+Y'
        pre_rotation = eulers[axis].to_quaternion()
        pre_perm = perms[axis]
        vnode['bone_pre_rotation_axis'] = axis
        vnode['bone_pre_rotation'] = pre_rotation
        vnode['bone_pre_perm'] = pre_perm

        # Apply the pre-rotation.
        r *= pre_rotation

        vnode['bone_tr'] = t, r

        interbone_dists.append(t.length)


        # Try getting a bone length for our parent. The length that makes its
        # tail meet our head is considered best. Since the tail always lies
        # along the +Y ray, the closer we are to the this ray the better our
        # length will be compared to the lgnths chosen by our siblings. This is
        # measured by the "goodness". Amoung siblings with equal goodness, we
        # pick the smaller length, so the parent's tail will meet the nearest
        # child.
        if vnode['parent']['type'] == 'BONE':
            t_len = t.length
            if t_len > 0.0005:
                goodness = t.dot(Vector((0,1,0))) / t_len
                if goodness > vnode['parent'].get('bone_length_goodness', -1):
                    if 'bone_length' not in vnode['parent'] or vnode['parent']['bone_length'] > t_len:
                        vnode['parent']['bone_length'] = t_len
                    vnode['parent']['bone_length_goodness'] = goodness

        # Recurse
        for child in vnode['children']:
            visit(child)

        # We're on the way back up. Last chance to set our bone length if none
        # of our children did. Use our parent's, if it has one. Otherwise, use
        # the average inter-bone distance, if its not 0. Otherwise, just use 1
        # -_-
        if 'bone_length' not in vnode:
            if 'bone_length' in vnode['parent']:
                vnode['bone_length'] = vnode['parent']['bone_length']
            else:
                avg = sum(interbone_dists) / max(1, len(interbone_dists))
                if avg > 0.0005:
                    vnode['bone_length'] = avg
                else:
                    vnode['bone_length'] = 1

    for arma_vnode in op.armature_vnodes:
        for child in arma_vnode['children']:
            visit(child)


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
            # Cancel out the pre-transform
            r = vnode.get('bone_pre_rotation', Quaternion((1,0,0,0)))
            s = vnode.get('bone_pre_scale', Quaternion((1,1,1)))
            # For bones, Blender puts a child at the tail, not the head (whyyy).
            # So we need to translate backwards along the bone's vector (= local
            # Y-axis).
            t = Vector((0, -vnode['bone_length'], 0))
        else:
            t, r, s = Vector((0,0,0)), Quaternion((1,0,0,0)), Vector((1,1,1))

        # Quarter-turn around the X-axis. Used to account for cameras or lights
        # that point along the -Z axis in Blender but glTF says should look
        # along the -Y axis
        x_rot = Quaternion((2**(-1/2), 2**(-1/2), 0, 0))

        if inst_kind == 'mesh_instance':
            id = inst['mesh']
            name = op.gltf['meshes'][id].get('name', 'meshes[%d]' % id)
        elif inst_kind == 'camera_instance':
            id = inst['camera']
            name = op.gltf['cameras'][id].get('name', 'cameras[%d]' % id)
            r *= x_rot
        elif inst_kind == 'light_instance':
            id = inst['light']
            lights = op.gltf['extenions']['KHR_lights_punctual']['lights']
            name = lights[id].get('name', 'lights[%d]' % id)
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

        if 'light_instance' in vnode:
            move_to_child(vnode, 'light_instance')

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

    return [Vector(loc), Quaternion(rot), Vector(sca)]


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
