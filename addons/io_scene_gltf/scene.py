import bpy
from mathutils import Vector, Matrix
from .vforest import create_vforest


def create_scenes(op):
    create_vforest(op)
    realize_vforest(op)
    link_forest_into_scenes(op)


def realize_vforest(op):
    """Create actual Blender nodes for the vnodes."""

    # See #16
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    def realize_vnode(vnode, parent_bone_mat=None):
        if vnode['type'] == 'NORMAL':
            data = None
            if 'mesh_instance' in vnode:
                inst = vnode['mesh_instance']
                data = op.get('mesh', inst['mesh'])
                # Set instance's morph target weights
                if inst['weights'] and data.shape_keys:
                    keyblocks = data.shape_keys.key_blocks
                    for i, weight in enumerate(inst['weights']):
                        if ('Morph %d' % i) in keyblocks:
                            keyblocks['Morph %d' % i].value = weight
            elif 'camera_instance' in vnode:
                inst = vnode['camera_instance']
                data = op.get('camera', inst['camera'])
            elif 'light_instance' in vnode:
                inst = vnode['light_instance']
                data = op.get('light', inst['light'])

            ob = bpy.data.objects.new(vnode['name'], data)
            vnode['blender_object'] = ob

            if 'trs' in vnode:
                t, r, s = vnode['trs']
                ob.location = t
                ob.rotation_mode = 'QUATERNION'
                ob.rotation_quaternion = r
                ob.scale = s

            if vnode['parent']:
                if 'blender_object' in vnode['parent']:
                    ob.parent = vnode['parent']['blender_object']
                else:
                    assert(vnode['parent']['type'] == 'BONE')
                    ob.parent = vnode['parent']['armature_vnode']['blender_object']
                    ob.parent_type = 'BONE'
                    ob.parent_bone = vnode['parent']['blender_name']

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

            # Bones transforms are given, not by giving their local-to-parent
            # transform, but by giving their origin and axes in armature space.
            # So we need the local-to-arma matrix.
            t, r = vnode['bone_tr']
            m = parent_bone_mat or Matrix.Identity(4)
            m *= Matrix.Translation(t) * r.to_matrix().to_4x4()

            bone.head = m * Vector((0, 0, 0))
            bone.tail = m * Vector((0, vnode['bone_length'], 0))
            bone.align_roll(m * Vector((0, 0, 1)) - bone.head)

            parent_bone_mat = m

            vnode['blender_editbone'] = bone
            # Remember the name too because trying to access
            # vnode['blender_editbone'].name after we exit editmode brings down
            # the wrath of heaven.
            vnode['blender_name'] = bone.name

            if vnode['parent']:
                if 'blender_editbone' in vnode['parent']:
                    bone.parent = vnode['parent']['blender_editbone']

        else:
            assert(False)

        for child in vnode['children']:
            realize_vnode(child, parent_bone_mat)

        if vnode['type'] == 'ARMATURE':
            # Exit edit mode when we're done creating an armature
            bpy.ops.object.mode_set(mode='OBJECT')

            # Now that we're back in object mode, unlink the armature; we'll
            # link it again later on in its proper place.
            bpy.context.scene.objects.unlink(vnode['blender_object'])

    for root in op.root_vnodes:
        realize_vnode(root)

    # On the second pass, do things that require us to know the names of the
    # Blender objects we create for each vnode.

    def pass2(vnode):
        # Create vertex groups for skinned meshes.
        if 'mesh_instance' in vnode and vnode['mesh_instance']['skin'] != None:
            ob = vnode['blender_object']
            skin = op.gltf['skins'][vnode['mesh_instance']['skin']]
            joints = skin['joints']

            for node_id in joints:
                bone_name = op.id_to_vnode[node_id]['blender_name']
                ob.vertex_groups.new(bone_name)

            mod = ob.modifiers.new('Skin', 'ARMATURE')
            armature_vnode = op.id_to_vnode[skin['joints'][0]]['armature_vnode']
            mod.object = armature_vnode['blender_object']
            mod.use_vertex_groups = True

            # TODO: we need to constrain the mesh to its armature so that its
            # world space position is affected only by the world space transform
            # of the joints and not of the node where it is instantiated, see
            # glTF/#1195. But note that this appears to break some sample models,
            # eg. Monster.

        for child in vnode['children']:
            pass2(child)

    for root in op.root_vnodes:
        pass2(root)

    # Warn about non-homogeneous scalings
    if op.bones_with_nonhomogeneous_scales:
        print(
            'WARNING! The following bones had non-homogeneous scalings:',
            *(b['blender_name'] for b in op.bones_with_nonhomogeneous_scales)
        )


def link_vnode(scene, vnode):
    if 'blender_object' in vnode:
        try:
            scene.objects.link(vnode['blender_object'])
        except Exception:
            # If it's already linked, shut up
            pass


def link_tree(scene, vnode):
    """Link all the Blender objects under vnode into the given Blender scene."""
    link_vnode(scene, vnode)
    for child in vnode['children']:
        link_tree(scene, child)


def link_forest_into_scenes(op):
    """Link the realized forest into scenes."""
    if op.import_under_current_scene:
        # Link everything into the current scene
        for root_vnode in op.root_vnodes:
            link_tree(bpy.context.scene, root_vnode)
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

                # A root glTF node isn't necessarily a root vnode. There might
                # be an armature above it.
                if 'armature_vnode' in vnode:
                    link_vnode(blender_scene, vnode['armature_vnode'])

                link_tree(blender_scene, vnode)

                # Select this scene if it is the default
                if i == default_scene_id:
                    bpy.context.screen.scene = blender_scene
