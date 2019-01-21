from math import pi
from mathutils import Matrix, Quaternion, Vector, Euler

# The node graph in glTF needs to fixed up quite a bit before it will work for
# Blender. We first create a graph of "virtual nodes" to match the graph in the
# glTF file and then transform it in a bunch of passes to make it suitable for
# Blender import.

class VNode:
    def __init__(self):
        # The ID of the glTF node this vnode was created from, or None if there
        # wasn't one
        self.node_id = None
        # List of child vnodes
        self.children = []
        # Parent vnode, or None for the root
        self.parent = None
        # (Vector, Quaternion, Vector) triple of the local-to-parent TRS transform
        self.trs = (Vector((0, 0, 0)), Quaternion((1, 0, 0, 0)), Vector((1, 1, 1)))

        # What type of Blender object will be created for this vnode: one of
        # OBJECT, ARMATURE, BONE, or the special value IMAGINARY_ROOT. The
        # IMAGINARY_ROOT doesn't get realized as anything in Blender, but having
        # the whole graph be a tree instead of a forest makes certain graph
        # processing easier.
        self.type = 'OBJECT'

        # Dicts of instance data
        self.mesh = None
        self.camera = None
        self.light = None
        # If this node had an instance in glTF but we moved it to another node,
        # we record where we put it here
        self.mesh_moved_to = None
        self.camera_moved_to = None
        self.light_moved_to = None

        # These will be filled out after realization with the Blender data
        # created for this vnode.
        self.blender_object = None
        self.blender_armature = None
        self.blender_editbone = None
        self.blender_name = None

        # The editbone's (Translation, Rotation)
        self.editbone_tr = None
        self.editbone_local_to_armature = Matrix.Identity(4)
        self.bone_length = 0
        # Correction to apply to the original TRS to get the editbone TR
        self.correction_rotation = Quaternion((1, 0, 0, 0))
        self.correction_homscale = 1
        self.correction_rotation_axis = '+Y'
        self.correction_rotation_permutation = [0, 1, 2]

        # Cache of actions that use an armature; used in importing animations
        self.armature_action_cache = {}


def create_vtree(op):
    initial_vtree(op)
    insert_armatures(op)
    move_instances(op)
    adjust_bones(op)


# In the first pass, create the vgraph from the forest from the glTF file,
# making one OBJECT for each node
#
#       OBJ
#      /  \
#     OBJ  OBJ
#         /  \
#       OBJ   OBJ
#
# (The imaginary root is also added, but we won't draw it)
def initial_vtree(op):
    nodes = op.gltf.get('nodes', [])

    op.node_id_to_vnode = {}

    # Create a vnode for each node
    for node_id, node in enumerate(nodes):
        vnode = VNode()
        vnode.node_id = node_id
        vnode.name = node.get('name', 'nodes[%d]' % node_id)
        vnode.trs = get_node_trs(node)
        vnode.type = 'OBJECT'

        if 'mesh' in node:
            vnode.mesh = {
                'mesh': node['mesh'],
                'skin': node.get('skin'),
                'weights': node.get('weights', op.gltf['meshes'][node['mesh']].get('weights')),
            }
        if 'camera' in node:
            vnode.camera = {
                'camera': node['camera'],
            }
        if 'KHR_lights_punctual' in node.get('extensions', {}):
            vnode.light = {
                'light': node['extensions']['KHR_lights_punctual']['light'],
            }

        op.node_id_to_vnode[node_id] = vnode

    # Fill in the parent/child relationships
    for node_id, node in enumerate(nodes):
        vnode = op.node_id_to_vnode[node_id]
        for child_id in node.get('children', []):
            child_vnode = op.node_id_to_vnode[child_id]

            # Prevent cycles
            assert(child_vnode.parent == None)

            child_vnode.parent = vnode
            vnode.children.append(child_vnode)

    # Add a root node to make the forest of vnodes into a tree.
    op.root_vnode = VNode()
    op.root_vnode.type = 'IMAGINARY_ROOT'

    for vnode in op.node_id_to_vnode.values():
        if vnode.parent == None:
            vnode.parent = op.root_vnode
            op.root_vnode.children.append(vnode)


# There is no special kind of node used for skinning in glTF. Joints are just
# regular nodes. But in Blender, only a bone can be used for skinning and bones
# are descendants of armatures.
#
# In the second pass we insert enough ARMATURE vnodes into the vtree so that
# every vnode which is the joint of a skin is a descendant of an ARMATURE. All
# descendants of ARMATURES are then turned into bones.
#
#       OBJ
#      /  \
#    OBJ  ARMA
#          |
#         BONE
#         /  \
#      BONE   BONE
def insert_armatures(op):
    # Insert an armature for every skin
    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):
        armature = VNode()
        armature.name = skin.get('name', 'skins[%d]' % skin_id)
        armature.type = 'ARMATURE'

        # We're going to find a place to insert the armature. It must be above
        # all of the joint nodes.
        vnodes_below = [op.node_id_to_vnode[joint_id] for joint_id in skin['joints']]
        # Add in the skeleton node too (which we hope is an ancestor of the joints).
        if 'skeleton' in skin:
            vnodes_below.append(op.node_id_to_vnode[skin['skeleton']])

        ancestor = lowest_common_ancestor(vnodes_below)

        ancestor_is_joint = ancestor.node_id in skin['joints']
        if ancestor_is_joint:
            insert_above(ancestor, armature)
        else:
            insert_below(ancestor, armature)

    # Walk down the tree, marking all children of armatures as bones and
    # deleting any armature which is a descendant of another.
    def visit(vnode, armature_ancestor):
        # Make a copy of this because we don't want it to change (when we delete
        # a vnode) while we're in the middle of iterating it
        children = list(vnode.children)

        # If we are below an armature...
        if armature_ancestor:
            # Found an armature descended of another
            if vnode.type == 'ARMATURE':
                remove_vnode(vnode)

            else:
                vnode.type = 'BONE'
                vnode.armature_vnode = armature_ancestor

        else:
            if vnode.type == 'ARMATURE':
                armature_ancestor = vnode

        for child in children:
            visit(child, armature_ancestor)

    visit(op.root_vnode, None)


# Now we need to enforce Blender's rule that (1) and object may have only one
# data instance (ie. only one of a mesh or a camera or a light), and (2) a bone
# may not have a data instance at all. We also need to move all cameras/lights
# to new children so that we have somewhere to hang the glTF->Blender axis
# conversion they need.
#
#
#             OBJ               Eg. if there was a mesh and camera on OBJ1
#            /  \               we will move the camera to a new child OBJ3
#        OBJ1   ARMA            (leaving the mesh on OBJ1).
#         /      |              And if there was a mesh on BONE2 we will move
#     OBJ3      BONE            the mesh to OBJ4
#               /  \
#            BONE   BONE2
#                    |
#                   OBJ4
def move_instances(op):
    def move_instance_to_new_child(vnode, key):
        inst = getattr(vnode, key)
        setattr(vnode, key, None)

        if key == 'mesh':
            id = inst['mesh']
            name = op.gltf['meshes'][id].get('name', 'meshes[%d]' % id)
        elif key == 'camera':
            id = inst['camera']
            name = op.gltf['cameras'][id].get('name', 'cameras[%d]' % id)
        elif key == 'light':
            id = inst['light']
            lights = op.gltf['extensions']['KHR_lights_punctual']['lights']
            name = lights[id].get('name', 'lights[%d]' % id)
        else:
            assert(False)

        new_child = VNode()
        new_child.name = name
        new_child.parent = vnode
        vnode.children.append(new_child)
        new_child.type = 'OBJECT'

        setattr(new_child, key, inst)
        setattr(vnode, key + '_moved_to', new_child)

        if key in ['camera', 'light']:
            # Quarter-turn around the X-axis. Needed for cameras or lights that
            # point along the -Z axis in Blender but glTF says should look along the
            # -Y axis
            new_child.trs = (
                new_child.trs[0],
                Quaternion((2**(-1/2), 2**(-1/2), 0, 0)),
                new_child.trs[2]
            )

        return new_child


    def visit(vnode):
        # Make a copy of this so we don't re-process new children we just made
        children = list(vnode.children)

        # Always move a camera or light to a child because it needs the
        # gltf->Blender axis conversion
        if vnode.camera:
            move_instance_to_new_child(vnode, 'camera')
        if vnode.light:
            move_instance_to_new_child(vnode, 'light')

        if vnode.mesh and vnode.type == 'BONE':
            move_instance_to_new_child(vnode, 'mesh')

        for child in children:
            visit(child)

    visit(op.root_vnode)


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
# we choose per-bone coordinate changes C(b) = Cs(b) Cr(b) (Cs(b) is a scaling,
# Cr(b) is a rotation) and replace
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
# translation of P(b) (and C), the rotation depends only on the rotation, etc.
# This failure means we would not be able to calculate animation curves
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
# If the rest scalings are all homogeneous, then the Cs(b) scalings are also
# homogeneous and this assumption is justified. What if your model had
# non-homogeneous rest scalings? Too bad, we assume it anyway! You're lucky we'll
# even look at your crummy model, ya dog. Maybe you'll get a warning. Anyway
# it's not clear to me that it's possible in general to retarget a bind pose
# that uses non-homogeneous scalings onto one that doesn't use any scalings
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
# animation importing) which we have not restricted to being homogeneous.
def adjust_bones(op):
    axes = {
        '-X': Vector((-1,  0,  0)),
        '+X': Vector((1,  0,  0)),
        '-Y': Vector((0, -1,  0)),
        '-Z': Vector((0,  0, -1)),
        '+Z': Vector((0,  0,  1)),
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

    def visit_bone(vnode):
        t, r, s = vnode.trs

        # TODO: unimplemented
        if not is_non_degenerate_homscale(s):
            raise Exception("unimplemented: bone has degenerate or non-homogeneous scaling")
        s = s[0]

        # Apply C(pb)^{-1} = Cr(pb)^{-1} Cs(pb)^{-1} = Rot[post_rotate] Scale[post_scale]
        post_rotation = vnode.parent.correction_rotation.conjugated()
        post_homscale = 1 / vnode.parent.correction_homscale
        # Rot[post_rotate] Scale[post_scale] Trans[t] Rot[r] Scale[s] =
        # Trans[Rot[post_rotate] Scale[post_scale] t] Rot[post_rotate * r] Scale[post_scale * s]
        t = post_rotation.to_matrix() * t
        t = post_homscale * t
        r = post_rotation * r
        s = post_homscale * s

        # Choose a pre-scaling that will cancel out our scaling, s.
        vnode.correction_homscale = 1 / s

        # Choose a pre-rotation
        axis = None
        if op.bone_rotation_mode == 'MANUAL':
            axis = op.bone_rotation_axis
        elif op.bone_rotation_mode == 'AUTO':
            # We choose an axis that makes our tail close to the head of the
            # one of our children
            def guess_axis():
                for child in vnode.children:
                    head = s * child.trs[0]
                    length = head.length
                    if length > 0.0005:
                        for axis_name, vec in axes.items():
                            if (vec * length - head).length < length * 0.25:
                                return axis_name
                return None

            axis = guess_axis()
            # Otherwise use the same axis our parent used
            if not axis:
                axis = getattr(vnode.parent, 'correction_rotation_axis', '+Y')
        elif op.bone_rotation_mode == 'NONE':
            axis = '+Y'
        pre_rotation = eulers[axis].to_quaternion()
        pre_perm = perms[axis]
        vnode.correction_rotation_axis = axis
        vnode.correction_rotation = pre_rotation
        vnode.correction_rotation_permutation = pre_perm

        # Apply the pre-rotation.
        r *= pre_rotation

        vnode.editbone_tr = t, r
        vnode.editbone_local_to_armature = (
            vnode.parent.editbone_local_to_armature *
            Matrix.Translation(t) * r.to_matrix().to_4x4()
        )

        interbone_dists.append(t.length)

        # Try getting a bone length for our parent. The length that makes its
        # tail meet our head is considered best. Since the tail always lies
        # along the +Y ray, the closer we are to the this ray the better our
        # length will be compared to the lgnths chosen by our siblings. This is
        # measured by the "goodness". Amoung siblings with equal goodness, we
        # pick the smaller length, so the parent's tail will meet the nearest
        # child.
        vnode.bone_length_goodness = -99999
        if vnode.parent.type == 'BONE':
            t_len = t.length
            if t_len > 0.0005:
                goodness = t.dot(Vector((0, 1, 0))) / t_len
                if goodness > vnode.parent.bone_length_goodness:
                    if vnode.parent.bone_length == 0 or vnode.parent.bone_length > t_len:
                        vnode.parent.bone_length = t_len
                    vnode.parent.bone_length_goodness = goodness

        # Recurse
        for child in vnode.children:
            visit_bone(child)

        # We're on the way back up. Last chance to set our bone length if none
        # of our children did. Use our parent's, if it has one. Otherwise, use
        # the average inter-bone distance, if its not 0. Otherwise, just use 1
        # -_-
        if not vnode.bone_length:
            if vnode.parent.bone_length:
                vnode.bone_length = vnode.parent.bone_length
            else:
                avg = sum(interbone_dists) / max(1, len(interbone_dists))
                if avg > 0.0005:
                    vnode.bone_length = avg
                else:
                    vnode.bone_length = 1

    def visit(vnode):
        if vnode.type == 'ARMATURE':
            for child in vnode.children:
                visit_bone(child)
        else:
            for child in vnode.children:
                visit(child)

    visit(op.root_vnode)

    # TODO: apply correction to object-children of bones


# Helper functions below here:

def get_node_trs(node):
    """Gets the TRS proerties from a glTF node JSON object."""
    if 'matrix' in node:
        m = node['matrix']
        # column-major to row-major
        m = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        m.transpose()
        loc, rot, sca = m.decompose()
    else:
        sca = node.get('scale', [1.0, 1.0, 1.0])
        rot = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
        rot = [rot[3], rot[0], rot[1], rot[2]]  # xyzw -> wxyz
        loc = node.get('translation', [0.0, 0.0, 0.0])

    # Switch glTF coordinates to Blender coordinates
    sca = [sca[0], sca[2], sca[1]]
    rot = [rot[0], rot[1], -rot[3], rot[2]]
    loc = [loc[0], -loc[2], loc[1]]

    return [Vector(loc), Quaternion(rot), Vector(sca)]


def lowest_common_ancestor(vnodes):
    """
    Compute the lowest common ancestors of vnodes, ie. the lowest node of which
    all the given vnodes are (possibly impromper) descendants.
    """
    assert(vnodes)

    def ancestor_list(vnode):
        """
        Computes the ancestor-list of vnode: the list of all its ancestors
        starting at the root and ending at vnode itself.
        """
        chain = []
        while vnode:
            chain.append(vnode)
            vnode = vnode.parent
        chain.reverse()
        return chain

    def first_difference(l1, l2):
        """
        Returns the index of the first difference in two lists, or None if one is
        a prefix of the other.
        """
        i = 0
        while True:
            if i == len(l1) or i == len(l2):
                return None
            if l1[i] != l2[i]:
                return i
            i += 1

    # Ancestor list for the lowest common ancestor so far
    lowest_ancestor_list = ancestor_list(vnodes[0])

    for vnode in vnodes[1:]:
        cur_ancestor_list = ancestor_list(vnode)
        d = first_difference(lowest_ancestor_list, cur_ancestor_list)
        if d is None:
            if len(cur_ancestor_list) < len(lowest_ancestor_list):
                lowest_ancestor_list = cur_ancestor_list
        else:
            lowest_ancestor_list = lowest_ancestor_list[:d]

    return lowest_ancestor_list[-1]


def insert_above(vnode, new_parent):
    """
    Inserts new_parent between vnode and its parent. That is, turn

        parent -> sister              parent -> sister
               -> vnode      into            -> new_parent -> vnode
               -> sister                     -> sister
    """
    if not vnode.parent:
        vnode.parent = new_parent
        new_parent.parent = None
        new_parent.children = [vnode]
    else:
        parent = vnode.parent
        i = parent.children.index(vnode)
        parent.children[i] = new_parent
        new_parent.parent = parent
        new_parent.children = [vnode]
        vnode.parent = new_parent


def insert_below(vnode, new_child):
    """
    Insert new_child between vnode and its children. That is, turn

        vnode -> child              vnode -> new_child -> child
              -> child     into                        -> child
              -> child                                 -> child
    """
    children = vnode.children
    vnode.children = [new_child]
    new_child.parent = vnode
    new_child.children = children
    for child in children:
        child.parent = new_child


def remove_vnode(vnode):
    """
    Remove vnode from the tree, replacing it with its children. That is, turn

        parent -> sister                  parent -> sister
               -> vnode -> child   into          -> child
               -> sister                         -> sister
    """
    assert(vnode.parent) # will never be called on the root

    parent = vnode.parent
    children = vnode.children

    i = parent.children.index(vnode)
    parent.children = (
        parent.children[:i] +
        children +
        parent.children[i+1:]
    )
    for child in children:
        child.parent = parent

    vnode.parent = None
    vnode.children = []


def is_non_degenerate_homscale(s):
    """Returns true if Scale[s] is multiplication by a non-zero scalar."""
    largest = max(abs(x) for x in s)
    smallest = min(abs(x) for x in s)

    if smallest < 1e-10:
        # Too small; consider it zero
        return False
    return largest - smallest < largest * 0.001
