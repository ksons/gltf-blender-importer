from mathutils import Vector, Quaternion, Matrix
import bpy
from . import quote
from .curve import Curve

# Handles animating TRS properties for glTF nodes. In Blender, this can be
# either an object or a bone.


def add_node_trs_animation(op, anim_id, node_id, samplers):
    if op.node_id_to_vnode[node_id].type == 'BONE':
        bone_trs(op, anim_id, node_id, samplers)
    else:
        object_trs(op, anim_id, node_id, samplers)


# Convert from glTF coordinates to Blender.
def convert_translation(t):
    return Vector([t[0], -t[2], t[1]])


def convert_rotation(r):
    return Quaternion([r[3], r[0], -r[2], r[1]])


def convert_scale(s):
    return Vector([s[0], s[2], s[1]])


def object_trs(op, animation_id, node_id, samplers):
    # Create action
    animation = op.gltf['animations'][animation_id]
    blender_object = op.node_id_to_vnode[node_id].blender_object
    name = '%s@%s' % (
        animation.get('name', 'animations[%d]' % animation_id),
        blender_object.name,
    )
    action = bpy.data.actions.new(name)
    action.use_fake_user = True

    # Play the first animation by default
    if animation_id == 0:
        blender_object.animation_data_create().action = action

    if 'translation' in samplers:
        curve = Curve.for_sampler(op, samplers['translation'])
        fcurves = curve.make_fcurves(
            op, action, 'location',
            transform=convert_translation)

        group = action.groups.new('Location')
        for fcurve in fcurves:
            fcurve.group = group

    if 'rotation' in samplers:
        curve = Curve.for_sampler(op, samplers['rotation'])
        curve.shorten_quaternion_paths()
        fcurves = curve.make_fcurves(
            op, action, 'rotation_quaternion',
            transform=convert_rotation)

        group = action.groups.new('Rotation')
        for fcurve in fcurves:
            fcurve.group = group

    if 'scale' in samplers:
        curve = Curve.for_sampler(op, samplers['scale'])
        fcurves = curve.make_fcurves(
            op, action, 'scale',
            transform=convert_scale)

        group = action.groups.new('Scale')
        for fcurve in fcurves:
            fcurve.group = group


def bone_trs(op, anim_id, node_id, samplers):
    # Unlike an object, a bone doesn't get its own action; there is one action
    # for the whole armature. To handle this, we store a cache of the action for
    # each animation in the armature's vnode and create one when we first
    # animate a bone in that armature.
    bone_vnode = op.node_id_to_vnode[node_id]
    armature_vnode = bone_vnode.armature_vnode
    action_cache = armature_vnode.armature_action_cache
    if anim_id not in action_cache:
        name = '%s@%s' % (
            op.gltf['animations'][anim_id].get('name', 'animations[%d]' % anim_id),
            armature_vnode.blender_armature.name,
        )
        action = bpy.data.actions.new(name)
        action_cache[anim_id] = action
        action.use_fake_user = True

        # Play the first animation by default
        if anim_id == 0:
            bl_object = armature_vnode.blender_object
            bl_object.animation_data_create().action = action

    action = action_cache[anim_id]

    # See vforest.py for the notation and assumptions used here.
    #
    # In glTF, the ordinates of an animation curve say what the final position
    # of the node should be
    #
    #     T(b) = sample_gltf_curve()
    #
    # But in Blender, you animate a "pose bone", and the final position is
    # computed relative to the rest position as
    #
    #     P'(b) = sample_blender_curve()
    #     T'(b) = E'(b) P'(b)
    #
    # where the primed varaibles have had a coordinate change to modify the bind
    # pose (again, see vforest.py). Calculating the value we need for P'(b) from
    # the value we have for T(b)
    #
    #     P'(b) =
    #     E'(b)^{-1} T'(b) =
    #     E'(b)^{-1} C(pb)^{-1} T(b) C(b) =
    #      {remember that E' do not contain a scale and the C do not contain a translation}
    #     Rot[er^{-1}] Trans[-et] Scale[post_s] Rot[post_r] Trans[t] Rot[r] Scale[s] Scale[pre_s] Rot[pre_r] =
    #      {lift the translations up}
    #     Trans[Rot[er^{-1}](-et) + Rot[er^{-1}] Scale[post_s] Rot[post_r] t] ...
    #
    # Defining pt = (the expression inside the Trans there)
    #
    #     Trans[pt] Rot[er^{-1}] Scale[post_s] Rot[post_r] Rot[r] Scale[s] Scale[pre_s] Rot[pre_r] =
    #      {by fiat, Scale[post_s] and Scale[pre_s] commute with rotations}
    #     Trans[pt] Rot[er^{-1}] Rot[post_r] Rot[r] Scale[post_s] Scale[s] Rot[pre_r] Scale[pre_s] =
    #      {using Scale[s] Rot[pre_r] = Rot[pre_r] Scale[s'] where s' is s permuted}
    #     Trans[pt] Rot[er^{-1} * post_r * r] Scale[post_s] Rot[pre_r] Scale[s'] Scale[pre_s] =
    #     Trans[pt] Rot[er^{-1} * post_r * r * pre_r] Scale[post_s * s' * pre_s] =
    #     Trans[pt] Rot[pr] Scale[ps]
    #
    # As we promised, pt depends only on t, pr depends only on r, and ps depends
    # only on s (ignoring constants), so each curve only has its ordinates
    # changed and they are still independent and don't need to be resampled.

    et, er = bone_vnode.editbone_tr
    inv_er, inv_et = er.conjugated(), -et

    parent_pre_r = bone_vnode.parent.correction_rotation
    parent_pre_s = bone_vnode.parent.correction_homscale
    post_r = parent_pre_r.conjugated()
    post_s = 1 / parent_pre_s

    pre_r = bone_vnode.correction_rotation
    pre_s = bone_vnode.correction_homscale

    if 'translation' in samplers:
        # pt = Rot[er^{-1}](-et) + Rot[er^{-1}] Scale[post_s] Rot[post_r] t
        #    = c + m t
        inv_er_mat = inv_er.to_matrix().to_4x4()
        post_s_mat = post_s * Matrix.Identity(4)
        c = inv_er_mat * inv_et
        m = inv_er_mat * post_s_mat * post_r.to_matrix().to_4x4()

        def transform_translation(t): return c + m * convert_translation(t)

        # In order to transform the tangents for cubic interpolation, we need to
        # know how the derivative transforms too. The other transforms are
        # linear, so their derivatives change the same way they do, but
        # transform_translation is affine, so its derivative changes by its
        # underlying linear map.
        def transform_velocity(t): return m * convert_translation(t)

    if 'rotation' in samplers:
        # pt = er^{-1} * post_r * r * pre_r
        #    = d * r * pre_r
        d = inv_er * post_r

        def transform_rotation(r): return d * convert_rotation(r) * pre_r

    if 'scale' in samplers:
        # ps = post_s * s' * pre_s
        perm = bone_vnode.correction_rotation_permutation

        def transform_scale(s):
            s = convert_scale(s)
            s = Vector((s[perm[0]], s[perm[1]], s[perm[2]]))
            return post_s * pre_s * s

    bone_name = bone_vnode.blender_name
    base_path = 'pose.bones[%s]' % quote(bone_name)

    fcurves = []

    if 'translation' in samplers:
        curve = Curve.for_sampler(op, samplers['translation'])
        fcurves += curve.make_fcurves(
            op, action, base_path + '.location',
            transform=transform_translation,
            tangent_transform=transform_velocity)

    if 'rotation' in samplers:
        curve = Curve.for_sampler(op, samplers['rotation'])
        # NOTE: it doesn't matter that we're shortening before we transform
        # because transform_rotation preserves the dot product
        curve.shorten_quaternion_paths()
        fcurves += curve.make_fcurves(
            op, action, base_path + '.rotation_quaternion',
            transform=transform_rotation)

    if 'scale' in samplers:
        curve = Curve.for_sampler(op, samplers['scale'])
        fcurves += curve.make_fcurves(
            op, action, base_path + '.scale',
            transform=transform_scale)

    group = action.groups.new(bone_name)
    for fcurve in fcurves:
        fcurve.group = group
