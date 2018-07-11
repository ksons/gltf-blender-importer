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
#         1   2      joints: [2,3,4]          1   * <- Armature
#            / \   }]                              \
#           3   4                                   2 <- bone
#                                                  / \
#                                         bone -> 3   4 <- bone
#
#    Note that nodes listed in the joints array for a skin become bones in
#    Blender. This imposes the following limitation on the glTF files we can
#    handle: skins must not overlap. There is also some difficulty when not all
#    the children of an Armature vnode are bones.
#
#    Note that because of this, a glTF that is a root may not correspond to a
#    vnode that is a root (because a dummy Armature might have been inserted
#    above it).
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
# 3. Meshes on bone vnodes
#
#    Blender bones cannot have a mesh so any vnode that is a bone needs to have
#    a dummy child inserted to hold the mesh just like a dummy child is always
#    inserted for cameras.
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
# TODO: we might also need dummies between an object that has a bone parent (to
# move it from tail to head, see TODO below)

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
            'skeleton_root': None,
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
    # parent (if any) and mark bone nodes.
    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):

        if 'skeleton' not in skin:
            raise Exception('unimplemented: skin missing skeleton attribute')
        skeleton_root_id = skin['skeleton']
        skeleton_root = id_to_vnode[skeleton_root_id]

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

        # Mark all the children of the armature as being contained in that
        # armature; we detect overlapping skins and bail in this pass.
        def mark_containing_armature(vnode):
            if 'armature_vnode' in vnode:
                raise Exception('unsupported: a node (ID=%d) belongs to two different skins' % vnode['gltf_id'])
            vnode['armature_vnode'] = armature
            for child in vnode['children']: mark_containing_armature(child)

        mark_containing_armature(skeleton_root)

        # Mark the joints as being of type 'BONE'
        # TODO: what happens when there are non-bones beneath an armature node?
        for joint_node_id in skin['joints']:
            vnode = id_to_vnode[joint_node_id]
            vnode['type'] = 'BONE'

        # A curious fact is that bone positions in Blender are not specified
        # relative to their parent but relative to the containing armature. We
        # compute the matrix relative to the armature for each bone now.
        def compute_bone_mats(vnode, parent_mat=Matrix.Identity(4)):
            mat = parent_mat
            if 'trs' in vnode:
                mat = parent_mat * trs_to_matrix(vnode['trs'])
            if vnode['type'] == 'BONE':
                vnode['bone_matrix'] = mat
            for child in vnode['children']:
                compute_bone_mats(child, Matrix(mat))

        compute_bone_mats(armature)


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
                    'name': op.gltf['meshes'][mesh_id].get('mesh', 'meshes[%d]' % mesh_id),
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

    def realize_vnode(vnode):
        if vnode['type'] == 'NORMAL':
            data = None
            if 'mesh_id' in vnode:
                data = op.get('mesh', vnode['mesh_id'])
            elif 'camera_id' in vnode:
                data = op.get('camera', vnode['camera_id'])

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
                    # TODO: the parent is a bone; we can do this but we might
                    # need a dummy node in between to move the object from the
                    # tail (where it naturally goes when we make it a child) to
                    # the head (where I think it should go)
                    print('warning: object had non-object parent; things might go wrong')

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

            bone.head = vnode['bone_matrix'] * Vector((0, 0, 0))
            bone.tail = vnode['bone_matrix'] * Vector((0, 1, 0))
            bone.align_roll(vnode['bone_matrix'] * Vector((0, 0, 1)) - bone.head)
            # TODO: detect and warn about non-uniform scalings here

            vnode['blender_editbone'] = bone
            # Remember the name because trying to access
            # vnode['blender_editbone'].name after we exit editmode brings down
            # the wrath of heaven.
            vnode['blender_name'] = bone.name

            if vnode['parent']:
                if 'blender_editbone' in vnode['parent']:
                    bone.parent = vnode['parent']['blender_editbone']
                elif vnode['parent']['type'] != 'ARMATURE':
                    # TODO: a bone is the child of an object; can we do this in
                    # Blender?
                    print('warn: bone had non-bone parent; things might go wrong')

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

        for child in vnode['children']:
            create_vertex_groups(child)

    for root in op.vnode_roots:
        create_vertex_groups(root)



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
                def find_root(vnode):
                    if vnode['parent'] == None: return vnode
                    return find_root(vnode['parent'])
                root_vnode = find_root(vnode)

                link_tree(blender_scene, root_vnode)

                # Select this scene if it is the default
                if i == default_scene_id:
                    bpy.context.screen.scene = blender_scene
