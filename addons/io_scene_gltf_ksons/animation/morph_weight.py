import bpy
from . import quote
from .curve import Curve

# Morph Weight Animations


def add_morph_weight_animation(op, anim_id, node_id, sampler):
    animation = op.gltf['animations'][anim_id]
    vnode = op.node_id_to_vnode[node_id]
    if vnode.mesh_moved_to:
        vnode = vnode.mesh_moved_to
    blender_object = vnode.blender_object

    if not blender_object.data.shape_keys:
        # Can happen if the mesh has only non-POSITION morph targets so we
        # didn't create a shape key
        return

    # Create action
    name = '%s@%s (Morph)' % (
        animation.get('name', 'animations[%d]' % anim_id),
        blender_object.name,
    )
    action = bpy.data.actions.new(name)
    action.id_root = 'KEY'
    action.use_fake_user = True

    # Play the first animation by default
    if anim_id == 0:
        blender_object.data.shape_keys.animation_data_create().action = action

    # Find out the number of morph targets
    mesh_id = op.gltf['nodes'][node_id]['mesh']
    mesh = op.gltf['meshes'][mesh_id]
    num_targets = len(mesh['primitives'][0]['targets'])

    curve = Curve.for_sampler(op, sampler, num_targets=num_targets)
    data_paths = [
        ('key_blocks[%s].value' % quote('Morph %d' % i), 0)
        for i in range(0, num_targets)
    ]

    curve.make_fcurves(op, action, data_paths)
