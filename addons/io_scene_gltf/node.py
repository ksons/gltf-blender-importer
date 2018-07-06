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
# an armature in which every glTF is realized as a bone, but this proved highly
# unpopular ("why is there an armature for a static mesh?!") :)
#
# So we create a heterogenous scene graph for the node forest. Every node in
# Blender's graph corresponds to a glTF node except
#
# - there is an armature object inserted between the root of a skin and its
#   parent
# - nodes which were the joints of a skin become bones for the armature inserted
#   for that skin; note that this imposes the following limitations on the glTF
#   -- we don't support overlapping skins: a node may be the child of the root
#      of only one skin
#   -- since a bone may not have a non-uniform scaling in its
#      rest position, any node used as a joint may not have a non-uniform scaling
#      TODO: actually scalings that aren't (1,1,1) aren't well tested at all.
# - there is an additional object to hold a mesh/camera inserted as a child of
#   objects whose glTF node held a "mesh"/"camera" property
#
# To assist creating this scene graph, we first build a "virtual forest"
# (vforest) of "virtual nodes" (vnodes) from the glTF which is a forest of
# Python objects that mirrors the forest we want to create in Blender. Then we
# realize the vforest by creating an actual Blender node for each vnode.
#
# Creating a virtual forest before creating the real one is easier since we can
# modify the vnodes types, etc. as be build it up progressively which is not so
# easy with actual Blender nodes. Also we can store additional data in the
# vforest that is consumed by eg. the script that creates animation (and needs
# to know rest TRS etc.).
#
#
# Example glTF:
#
#              1          skins: [
#             / \             {
#  {mesh: 0} 2   5                "skeleton": 5,
#               / \               "joints": [4,0,3,5]
#              0   4          }
#             /           ]
#            3
#
# Resulting vforest (nodes that don't correspond to a glTF node are written *):
#
#                1
#               / \
#              2   * <- armature
#             /     \
#  mesh 0 -> *       5 <- bone
#                   / \
#          bone -> 0   4 <- bone
#                 /
#        bone -> 3


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

    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):
        # Insert armatures for the skins between the root of the skin and their parent (if any).

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


    # Insert nodes for the meshes/cameras
    for id, node in enumerate(nodes):
        if 'mesh' in node:
            vnode = id_to_vnode[id]
            mesh_id = node['mesh']
            mesh = {
                'name': op.gltf['meshes'][mesh_id].get('name', 'meshes[%d]' % mesh_id),
                'children': [],
                'type': 'MESH',
                'mesh_id': mesh_id,
                'parent': vnode,
            }
            if 'skin' in node:
                mesh['skin'] = node['skin']
            vnodes.append(mesh)
            vnode['children'].append(mesh)
        if 'camera' in node:
            vnode = id_to_vnode[id]
            camera_id = node['camera']
            camera = {
                'name': op.gltf['cameras'][camera_id].get('name', 'cameras[%d]' % camera_id),
                'children': [],
                'type': 'CAMERA',
                'camera_id': camera_id,
                'parent': vnode,
            }
            vnodes.append(camera)
            vnode['children'].append(camera)

    # Find the roots of the forest
    vnode_roots = [vnode for vnode in vnodes if not vnode['parent']]

    op.vnodes = vnodes
    op.vnode_roots = vnode_roots
    op.id_to_vnode = id_to_vnode


def realize_vforest(op):
    """Create actual Blender nodes for the vnodes."""

    def realize_vnode(vnode):
        if vnode['type'] == 'NORMAL':
            ob = bpy.data.objects.new(vnode['name'], None)
            vnode['blender_object'] = ob

            loc, rot, sca = vnode['trs']
            ob.location = loc
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = rot
            ob.scale = sca

            if vnode['parent']:
                ob.parent = vnode['parent']['blender_object']

        elif vnode['type'] == 'MESH':
            data = op.get('mesh', vnode['mesh_id'])
            ob = bpy.data.objects.new(vnode['name'], data)
            vnode['blender_object'] = ob
            ob.parent = vnode['parent']['blender_object']

        elif vnode['type'] == 'CAMERA':
            data = op.get('camera', vnode['camera_id'])
            ob = bpy.data.objects.new(vnode['name'], data)
            vnode['blender_object'] = ob
            ob.parent = vnode['parent']['blender_object']

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
            if vnode['parent'] and 'blender_editbone' in vnode['parent']:
                bone.parent = vnode['parent']['blender_editbone']

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
        if vnode['type'] == 'MESH' and 'skin' in vnode:
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

                # A root of the glTF forest isn't necessarily a root of the vforest.
                # Find the real root.
                def find_root(vnode):
                    if vnode['parent'] == None: return vnode
                    return find_root(vnode['parent'])
                root_vnode = find_root(vnode)

                link_tree(blender_scene, root_vnode)

                # Select this scene if it is the default
                if i == default_scene_id:
                    bpy.context.screen.scene = blender_scene
