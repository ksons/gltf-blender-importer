import bpy
from mathutils import Matrix, Quaternion, Vector

# This file is responsible for creating the Blender scene graph from the glTF
# node forest.
#
# The glTF node forest is homogenous; every node is of the same kind and is
# transformed in the same way. It prefigures things like skinning or meshes
# which are layered on top of it. By contrast Blender's scene graph is highly
# heterogenous; there are different kinds of nodes and they are transformed in
# different ways.
#
# IMO it makes sense to import the node forest into a homogenous structure, like
# an armature in which every glTF node is realized as a bone, but this proved
# highly unpopular ("why is there an armature for a static mesh?!") :)
#
# So we create a heterogenous scene graph for the node forest. This is done in
# two steps: first we create a virtual forest ("vforest") of virtual nodes
# ("vnodes") with the structure we want, and then we realize the vforest as an
# actual Blender scene graph. Creating the vforest first makes it easier to
# build the structure we want up by progressive modification; another layer of
# indirection solves all problems, etc.
#
# Most vnodes correspond to a glTF node and are connected in the same hierarchy.
# Nodes that don't we'll call "dummies" (and write with a * in the diagrams
# below). They are created in the following situations.
#
# 1. Armatures
#
#    Every skin the glTF file has a dummy armature created for it. The armature
#    is inserted between the root of the skin and its parent (if it has one).
#
#         glTF:                              vforest:
#
#           0      skins: [{                    0
#          / \       skeleton: 2,              / \
#         1   2      joints: [3,4]            1   * <- Armature
#            / \   }]                              \
#           3   4                                   2 <- bone
#                                                  / \
#                                         bone -> 3   4 <- bone
#
#    Note that nodes all the child nodes of the skin's skeleton node become
#    bones regardless of whether they're joints in the skin. If two armatures
#    would overlap, only the ones that is "higher up" is kept.
#
#    Because of this, a glTF that is a root may not correspond to a vnode that
#    is a root (because a dummy Armature might have been inserted above it).
#
# 2. Cameras
#
#    If a node has both a mesh and camera, we can't put them both on it in
#    Blender, so we have to move at least one to a child. Which one should we
#    choose? Well, additionally, a camera needs a rotation on it to change from
#    glTF's convention for its pointing direction to Blender's. Consequently, we
#    choose to always create a dummy child to hold cameras.
#
#                    glTF:                        vforest:
#
#                      0                             0
#                     / \                           / \
#     mesh+camera -> 1   2 <- camera       mesh -> 1   2
#                                                 /     \
#                                      camera -> *       * <- camera
#
# 3. Meshes and cameras on bone vnodes
#
#    All nodes below an armature become bones in the vforest, but what if there
#    is a mesh or camera below a bone? Blender can handle this: you set the
#    parent of the object to the armature object, set the parent type to BONE
#    and set the parent bone to the desired bone. But this places the child
#    object at the tail of the bone: it should be at the head. So we need to
#    apply a translation along the tail-to-head vector to bring it back.
#
#    Of course, because of (2), cameras always already get a dummy node. So this
#    case is really about meshes.
#
#              glTF:                                vforest:
#
#                0      skins: [{                      * <- Armature
#               / \       skeleton: 0,                 |
#      mesh -> 1   2      joints: [0,1,2]              0 <- bone
#                       }]                            / \
#                                            bone -> 1   2 <- bone
#                                                   /
#                                          mesh -> *
#
#    Note that the structure of the vforest below an Aramature therefore
#    consists entirely of bones, except possibly the leaves, which may be dummy
#    nodes with meshes or cameras in them.

def create_scenes(op):
    create_vforest(op)
    realize_vforest(op)
    link_forest_into_scenes(op)


def create_vforest(op):
    nodes = op.gltf.get('nodes', [])

    # A list of all vnodes (the order isn't relevant but it makes it easy to
    # transverse them all to find the roots later on).
    vnodes = []
    # Maps an index into the gltf's nodes array to its corresponding vnode
    id_to_vnode = {}


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
        id_to_vnode[id] = vnode
        vnodes.append(vnode)


    # Fill in the parent/child relationships
    for id, node in enumerate(nodes):
        vnode = id_to_vnode[id]
        for child_id in node.get('children', []):
            child_vnode = id_to_vnode[child_id]
            child_vnode['parent'] = vnode
            vnode['children'].append(child_vnode)


    # Insert armatures for the skins between the root of the skin and their
    # parent (if any).
    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):

        if 'skeleton' not in skin:
            # Find the root of the tree that contains the joints (presumably
            # they must all be in the same tree)
            vnode = id_to_vnode[skin['joints'][0]]
            while vnode['parent']: vnode = vnode['parent']
            skeleton_root = vnode
        else:
            skeleton_root = id_to_vnode[skin['skeleton']]

        def insert_parent(vnode, parent):
            old_parent = vnode['parent']
            vnode['parent'] = parent
            parent['children'].append(vnode)
            if old_parent:
                pos = old_parent['children'].index(vnode)
                old_parent['children'][pos] = parent
                parent['parent'] = old_parent
            else:
                parent['parent'] = None

        armature = {
            'name': skin.get('name', 'skins[%d]' % skin_id),
            'children': [],
            'type': 'ARMATURE',
            'skin_id': skin_id,
            'parent': None,
        }
        vnodes.append(armature)
        insert_parent(skeleton_root, armature)


    # Mark all the children of armatures as bones and delete any armatures that
    # are the descendants of other armatures.

    def delete_vnode(vnode):
        if vnode['parent']:
            children = vnode['parent']['children']
            del children[children.index(vnode)]
        for child in vnode['children']:
            child.parent = vnode['parent']
        del vnodes[vnodes.index(vnode)]

    def process_bone(vnode, armature_vnode):
        if vnode['type'] == 'ARMATURE':
            delete_vnode(vnode)
        else:
            vnode['armature_vnode'] = armature_vnode
            vnode['type'] = 'BONE'

            # Record any non-unit scale so we can report about it later (Blender
            # bones appear to only allow unit scales)
            if 'trs' in vnode:
                t, r, s = vnode['trs']
                if any(abs(sx - 1) > 0.01 for sx in s):
                    vnode['had_nonunit_scale'] = True
                vnode['trs'] = (t, r, Vector((1, 1, 1)))

            # A curious fact is that bone positions in Blender are not specified
            # relative to their parent but relative to the containing armature.
            # We compute the matrix relative to the armature for each bone here.
            if vnode['parent'] and vnode['parent']['type'] == 'BONE':
                mat = vnode['parent']['bone_matrix']
            else:
                mat = Matrix.Identity(4)
            if 'trs' in vnode:
                mat = mat * trs_to_matrix(vnode['trs'])
            vnode['bone_matrix'] = mat

        for child in vnode['children']:
            process_bone(child, armature_vnode)

    armatures_vnodes = [vnode for vnode in vnodes if vnode['type'] == 'ARMATURE']
    for armature_vnode in armatures_vnodes:
        for child in armature_vnode['children']:
            process_bone(child, armature_vnode)


    # Register the meshes/cameras
    for id, node in enumerate(nodes):
        vnode = id_to_vnode[id]
        if 'mesh' in node:
            if vnode['type'] == 'NORMAL':
                vnode['mesh_id'] = node['mesh']
                if 'skin' in node:
                    vnode['skin'] = node['skin']
            else:
                mesh_id = node['mesh']
                mesh_vnode = {
                    'name': op.gltf['meshes'][mesh_id].get('name', 'meshes[%d]' % mesh_id),
                    'children': [],
                    'type': 'NORMAL',
                    'mesh_id': mesh_id,
                    'parent': vnode,
                }
                vnodes.append(mesh_vnode)
                vnode['children'].append(mesh_vnode)

        if 'camera' in node:
            camera_id = node['camera']
            camera_vnode = {
                'name': op.gltf['cameras'][camera_id].get('name', 'cameras[%d]' % camera_id),
                'children': [],
                'type': 'NORMAL',
                'camera_id': camera_id,
                'parent': vnode,
            }
            vnodes.append(camera_vnode)
            vnode['children'].append(camera_vnode)


    # Find the roots of the forest
    vnode_roots = [vnode for vnode in vnodes if not vnode['parent']]

    op.vnodes = vnodes
    op.vnode_roots = vnode_roots
    op.id_to_vnode = id_to_vnode


def realize_vforest(op):
    """Create actual Blender nodes for the vnodes."""

    # See #16
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    bone_rotate_mat = op.bone_rotation.to_matrix().to_4x4()

    any_objects_child_of_bone = [False] # detect this case so we can warn later
    # HACK: the usual wrap-it-in-an-array hack so it can be written to by an
    # inner function

    def realize_vnode(vnode):
        if vnode['type'] == 'NORMAL':
            data = None
            if 'mesh_id' in vnode:
                data = op.get('mesh', vnode['mesh_id'])
            elif 'camera_id' in vnode:
                data = op.get('camera', vnode['camera_id'])

            name = vnode['name']

            if vnode['parent'] and vnode['parent']['type'] == 'BONE':
                # We currently don't put this kind of object in the correct place
                # See TODO below. Mark its name so the user can tell.
                any_objects_child_of_bone[0] = True
                name = '[!!] ' + name

            ob = bpy.data.objects.new(vnode['name'], data)
            vnode['blender_object'] = ob

            if 'trs' in vnode:
                loc, rot, sca = vnode['trs']
                ob.location = loc
                ob.rotation_mode = 'QUATERNION'
                ob.rotation_quaternion = rot
                ob.scale = sca
            if 'camera_id' in vnode:
                # TODO: check this against the spec
                ob.rotation_mode = 'XYZ'
                ob.rotation_euler[0] = 1.5707963267948966

            if vnode['parent']:
                if 'blender_object' in vnode['parent']:
                    ob.parent = vnode['parent']['blender_object']
                else:
                    assert(vnode['parent']['type'] == 'BONE')
                    ob.parent = vnode['parent']['armature_vnode']['blender_object']
                    ob.parent_type = 'BONE'
                    ob.parent_bone = vnode['parent']['blender_name']

                    assert('trs' not in vnode)
                    # We need to apply a translation so the object is at the
                    # head of the bone, not the tail, like it normally is.
                    # TODO!!!!!!!
                    # NOTE: will probably involve the bone_rotation too.


        elif vnode['type'] == 'ARMATURE':
            # TODO: don't use ops here
            bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
            ob = bpy.context.object

            ob.location = [0, 0, 0]
            vnode['blender_armature'] = ob.data
            vnode['blender_object'] = ob

            if vnode['parent']:
                ob.parent = vnode['parent']['blender_object']


        elif vnode['type'] == 'BONE':
            armature = vnode['armature_vnode']['blender_armature']
            bone = armature.edit_bones.new(vnode['name'])
            bone.use_connect = False

            # Chose a length for the bone. The best one is so that its tail
            # meets the head of its (first) child, but fallback to the length of
            # its parent (if no children), or 1 (if no parent).
            bone_length = 1
            if vnode['parent'] and 'bone_length' in vnode['parent']:
                bone_length = vnode['parent']['bone_length']
            for child in vnode['children']:
                if child['type'] == 'BONE':
                    child_head = child['bone_matrix'] * Vector((0, 0, 0))
                    our_head = vnode['bone_matrix'] * Vector((0, 0, 0))
                    dist = (our_head - child_head).length
                    if dist != 0:
                        bone_length = dist
                        break
            vnode['bone_length'] = bone_length # record it for our children

            bone.head = vnode['bone_matrix'] * Vector((0, 0, 0))
            forward = bone_rotate_mat * Vector((0, bone_length, 0))
            side = bone_rotate_mat * Vector((0, 0, 1))
            bone.tail = vnode['bone_matrix'] * forward
            bone.align_roll(vnode['bone_matrix'] * side - bone.head)

            vnode['blender_editbone'] = bone

            # Remember the name because trying to access
            # vnode['blender_editbone'].name after we exit editmode brings down
            # the wrath of heaven.
            vnode['blender_name'] = bone.name

            if vnode['parent']:
                if 'blender_editbone' in vnode['parent']:
                    bone.parent = vnode['parent']['blender_editbone']
                else:
                    assert(vnode['parent']['type'] == 'ARMATURE')

        else:
            assert(False)

        for child in vnode['children']:
            realize_vnode(child)

        if vnode['type'] == 'ARMATURE':
            # Exit edit mode when we're done creating an armature
            bpy.ops.object.mode_set(mode='OBJECT')

            # Now that we're back in object mode, unlink the armature; we'll
            # link it again later on in its proper place.
            bpy.context.scene.objects.unlink(vnode['blender_object'])


    for root in op.vnode_roots:
        realize_vnode(root)


    # Now create the vertex groups for meshes; we do this in a second pass
    # because we need to have created all the bones so that we know what names
    # Blender will assign them before we can do this. (The actual joints/weights
    # were assigned as part of mesh creation.)
    def create_vertex_groups(vnode):
        if 'skin' in vnode:
            ob = vnode['blender_object']
            skin = op.gltf['skins'][vnode['skin']]
            joints = skin['joints']

            for node_id in joints:
                bone_name = op.id_to_vnode[node_id]['blender_name']
                ob.vertex_groups.new(bone_name)

            mod = ob.modifiers.new('Skin', 'ARMATURE')
            mod.object = op.id_to_vnode[skin['skeleton']]['armature_vnode']['blender_object']
            mod.use_vertex_groups = True

        # TODO: Don't we also need to do something about the skeleton root?

        for child in vnode['children']:
            create_vertex_groups(child)

    for root in op.vnode_roots:
        create_vertex_groups(root)


    # Report any warnings

    if any_objects_child_of_bone[0]:
        print(
            'Some objects (marked with [!!]) are almost surely in the wrong '
            'position. This is a known issue.'
        )

    bones_that_had_nonunit_scales = [
        vnode['blender_name']
        for vnode in op.vnodes
        if vnode.get('had_nonunit_scale', False)
    ]
    if bones_that_had_nonunit_scales:
        print(
            'Warning: the following bones had non-unit scalings '
            'which is not allowed: ',
            *bones_that_had_nonunit_scales
        )
        print('All their rest scalings have been set to 1.')




def trs_to_matrix(trs):
    loc, rot, sca = trs
    m = Matrix.Identity(4)
    m[0][0] = sca[0]
    m[1][1] = sca[1]
    m[2][2] = sca[2]
    m = rot.to_matrix().to_4x4() * m
    m = Matrix.Translation(loc) * m
    return m

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


def link_tree(scene, vnode):
    """Link all the Blender objects under vnode into the given Blender scene."""
    if 'blender_object' in vnode:
        scene.objects.link(vnode['blender_object'])
    for child in vnode['children']:
        link_tree(scene, child)

def link_forest_into_scenes(op):
    """Link the realized forest into scenes."""
    if op.import_under_current_scene:
        # Link everything into the current scene
        for root_vnode in op.vnode_roots:
            link_tree(bpy.context.scene, root_vnode)

        # Should we do this?
        bpy.context.scene.render.engine = 'CYCLES'

    else:
        # Creates scenes to match the glTF scenes

        default_scene_id = op.gltf.get('scene')

        scenes = op.gltf.get('scenes', [])
        for i, scene in enumerate(scenes):
            name = scene.get('name', 'scenes[%d]' % i)
            blender_scene = bpy.data.scenes.new(name)
            blender_scene.render.engine = 'CYCLES'

            roots = scene.get('nodes', [])
            for node_id in roots:
                vnode = op.id_to_vnode[node_id]

                # A root glTF node isn't necessarily a root vnode.
                # Find the real root.
                while vnode['parent']: vnode = vnode['parent']

                link_tree(blender_scene, vnode)

                # Select this scene if it is the default
                if i == default_scene_id:
                    bpy.context.screen.scene = blender_scene
