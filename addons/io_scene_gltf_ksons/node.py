import bpy
from mathutils import Vector, Matrix


def realize_vtree(op):
    """Create actual Blender nodes for the vnodes."""
    # Fix for #16
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    # First pass: depth-first realization of the vnode graph
    def realize_vnode(vnode):
        if vnode.type == 'OBJECT':
            realize_object(op, vnode)

        elif vnode.type == 'ARMATURE':
            realize_armature(op, vnode)

        elif vnode.type == 'BONE':
            realize_bone(op, vnode)

        for child in vnode.children:
            realize_vnode(child)

        # We enter edit-mode when we realize an armature. On the way back up,
        # we've finished creating edit bones and can go back to object mode.
        if vnode.type == 'ARMATURE':
            bpy.ops.object.mode_set(mode='OBJECT')

            # We'll link this in the right place later on.
            bpy.context.scene.objects.unlink(vnode.blender_object)

    realize_vnode(op.root_vnode)

    # Second pass for things that require we know the blender_object and
    # blender_name of the vnodes.
    def pass2(vnode):
        if vnode.mesh and vnode.mesh['skin'] != None:
            obj = vnode.blender_object

            # Create vertex groups.
            joints = op.gltf['skins'][vnode.mesh['skin']]['joints']
            for node_id in joints:
                bone_name = op.node_id_to_vnode[node_id].blender_name
                obj.vertex_groups.new(bone_name)

            # Create the skin modifier.
            modifier = obj.modifiers.new('Skin', 'ARMATURE')
            armature_vnode = op.node_id_to_vnode[joints[0]].armature_vnode
            modifier.object = armature_vnode.blender_object
            modifier.use_vertex_groups = True

            # TODO: we need to constrain the mesh to its armature so that its
            # world space position is affected only by the world space transform
            # of the joints and not of the node where it is instantiated, see
            # glTF/#1195. But note that this appears to break some sample models,
            # eg. Monster.

        for child in vnode.children:
            pass2(child)

    pass2(op.root_vnode)


def realize_object(op, vnode):
    """Create a real Object for an OBJECT vnode."""
    # Create the mesh/camera/light instance
    data = None
    if vnode.mesh:
        data = op.get('mesh', vnode.mesh['mesh'])

        # Set instance's morph target weights
        if vnode.mesh['weights'] and data.shape_keys:
            keyblocks = data.shape_keys.key_blocks
            for i, weight in enumerate(vnode.mesh['weights']):
                if ('Morph %d' % i) in keyblocks:
                    keyblocks['Morph %d' % i].value = weight

    elif vnode.camera:
        data = op.get('camera', vnode.camera['camera'])

    elif vnode.light:
        data = op.get('light', vnode.light['light'])

    obj = bpy.data.objects.new(vnode.name, data)
    vnode.blender_object = obj

    # Set TRS
    t, r, s = vnode.trs
    obj.location = t
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = r
    obj.scale = s

    # Set our parent
    if vnode.parent:
        if vnode.parent.type == 'OBJECT':
            obj.parent = vnode.parent.blender_object
        elif vnode.parent.type == 'BONE':
            obj.parent = vnode.parent.armature_vnode.blender_object
            obj.parent_type = 'BONE'
            obj.parent_bone = vnode.parent.blender_name


def realize_armature(op, vnode):
    """Create a real Armature for an ARMATURE vnode."""
    # TODO: find a way to avoid using ops and having to change modes
    bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
    obj = bpy.context.object

    vnode.blender_object = obj
    vnode.blender_armature = obj.data

    # Clear our location (ops.object.add puts the new armature at the location
    # of the 3D Cursor)
    obj.location = [0, 0, 0]

    if vnode.parent:
        obj.parent = vnode.parent.blender_object


def realize_bone(op, vnode):
    """Create a real EditBone for a BONE vnode."""
    armature = vnode.armature_vnode.blender_armature
    editbone = armature.edit_bones.new(vnode.name)

    editbone.use_connect = False

    # Bones transforms are given, not by giving their local-to-parent transform,
    # but by giving their head, tail, and roll in armature space. So we need the
    # local-to-armature transform.
    m = vnode.editbone_local_to_armature
    editbone.head = m * Vector((0, 0, 0))
    editbone.tail = m * Vector((0, vnode.bone_length, 0))
    editbone.align_roll(m * Vector((0, 0, 1)) - editbone.head)

    vnode.blender_name = editbone.name
    # NOTE: can't access this after we leave edit mode
    vnode.blender_editbone = editbone

    # Set parent
    if vnode.parent:
        if getattr(vnode.parent, 'blender_editbone', None):
            editbone.parent = vnode.parent.blender_editbone
