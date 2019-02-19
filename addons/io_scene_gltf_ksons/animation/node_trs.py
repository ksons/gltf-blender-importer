from mathutils import Vector, Quaternion, Matrix
import bpy
from . import quote
from .curve import Curve
from ..compat import mul

# Handles animating TRS properties for glTF nodes. In Blender, this can be
# either an object or a bone.


def add_node_trs_animation(op, anim_info, node_id):
    if op.node_id_to_vnode[node_id].type == 'BONE':
        bone_trs(op, anim_info, node_id)
    else:
        object_trs(op, anim_info, node_id)


def object_trs(op, anim_info, node_id):
    animation_id = anim_info.anim_id
    samplers = anim_info.node_trs[node_id]

    # Create action
    animation = op.gltf['animations'][animation_id]
    blender_object = op.node_id_to_vnode[node_id].blender_object
    name = '%s@%s' % (
        animation.get('name', 'animations[%d]' % animation_id),
        blender_object.name,
    )
    action = bpy.data.actions.new(name)
    anim_info.trs_actions[blender_object.name] = action
    action.use_fake_user = True

    # Play the first animation by default
    if animation_id == 0:
        blender_object.animation_data_create().action = action

    if 'translation' in samplers:
        curve = Curve.for_sampler(op, samplers['translation'])
        fcurves = curve.make_fcurves(
            op, action, 'location',
            transform=op.convert_translation)

        group = action.groups.new('Location')
        for fcurve in fcurves:
            fcurve.group = group

    if 'rotation' in samplers:
        curve = Curve.for_sampler(op, samplers['rotation'])
        curve.shorten_quaternion_paths()
        fcurves = curve.make_fcurves(
            op, action, 'rotation_quaternion',
            transform=op.convert_rotation)

        group = action.groups.new('Rotation')
        for fcurve in fcurves:
            fcurve.group = group

    if 'scale' in samplers:
        curve = Curve.for_sampler(op, samplers['scale'])
        fcurves = curve.make_fcurves(
            op, action, 'scale',
            transform=op.convert_scale)

        group = action.groups.new('Scale')
        for fcurve in fcurves:
            fcurve.group = group


def bone_trs(op, anim_info, node_id):
    anim_id = anim_info.anim_id
    samplers = anim_info.node_trs[node_id]

    # Unlike an object, a bone doesn't get its own action; there is one action
    # for the whole armature. Look it up or create it if it doesn't exist yet.
    bone_vnode = op.node_id_to_vnode[node_id]
    armature_vnode = bone_vnode.armature_vnode
    armature_object = armature_vnode.blender_object
    if armature_object.name not in anim_info.trs_actions:
        name = '%s@%s' % (
            op.gltf['animations'][anim_id].get('name', 'animations[%d]' % anim_id),
            armature_vnode.blender_armature.name,
        )
        action = bpy.data.actions.new(name)
        anim_info.trs_actions[armature_object.name] = action
        action.use_fake_user = True

        # Play the first animation by default
        if anim_id == 0:
            armature_object.animation_data_create().action = action

    action = anim_info.trs_actions[armature_object.name]

    # In glTF, the ordinates of an animation curve say what the final position
    # of the node should be
    #
    #     T(b) = sample_gltf_curve()
    #
    # But in Blender, you animate the pose bone, and the final position is
    # computed relative to the rest position as
    #
    #     P(b) = sample_blender_curve()
    #
    # and these are related as (see vnode.py for the notation used here)
    #
    #     T'(b) = C(pb)^{-1} T(b) C(b)
    #           = E(b) P(b)
    #
    # Computing
    #
    #       P(b)
    #     = E(b)^{-1} C(pb)^{-1} T(b) C(b)
    #     = Rot[er^{-1}] Trans[-et]
    #       Rot[cr(pb)^{-1}] HomScale[1/cs(pb)]
    #       Trans[t] Rot[r] Scale[s]
    #       Rot[cr(b)] HomScale[cs(b)]
    #
    #     { float the Trans to the left }
    #     = Trans[Rot[er^{-1}](-et + Rot[cr(pb)^{-1}] t / cs(pb))]
    #       Rot[er^{-1}] Rot[cr(pb)^{-1}] HomScale[1/cs(pb)]
    #       Rot[r] Scale[s]
    #       Rot[cr(b)] HomScale[cs(b)]
    #
    #     { combine scalings }
    #     = Trans[Rot[er^{-1}](-et + Rot[cr(pb)^{-1}] t / cs(pb))]
    #       Rot[er^{-1}] Rot[cr(pb)^{-1}]
    #       Rot[r] Scale[s cs(b) / cs(pb)]
    #       Rot[cr(b)]
    #
    #     { interchange the final Rot and Scale, permuting the scale
    #       (see exchange_scale_rot_matrix) }
    #     = Trans[Rot[er^{-1}](-et + Rot[cr(pb)^{-1}] t / cs(pb))]
    #       Rot[er^{-1}] Rot[cr(pb)^{-1}]
    #       Rot[r] Rot[cr(b)]
    #       Scale[M s cs(b) / cs(pb)]
    #
    #     { combine rotations }
    #     = Trans[Rot[er^{-1}](-et + Rot[cr(pb)^{-1}] t / cs(pb))]
    #       Rot[er^{-1} cr(pb)^{-1} r cr(b)]
    #       Scale[M s cs(b) / cs(pb)]
    #     = Trans[pt] Rot[pr] Scale[ps]
    #
    # Note that pt depends only on t (and not r or s), and similarly for pr and
    # ps.

    et, er = bone_vnode.editbone_tr
    cr_pb = bone_vnode.parent.correction_rotation
    cs_pb = bone_vnode.parent.correction_homscale
    cr = bone_vnode.correction_rotation
    cs = bone_vnode.correction_homscale

    er_inv = er.conjugated()
    cr_pb_inv = cr_pb.conjugated()
    cs_pb_inv = 1 / cs_pb

    if 'translation' in samplers:
        # pt = Rot[er^{-1}](-et + Rot[cr(pb)^{-1}] t / cs(pb))
        trans_mat = mul(
            er_inv.to_matrix().to_4x4(),
            mul(
                Matrix.Translation(-et),
                (cs_pb_inv * cr_pb_inv.to_matrix()).to_4x4()
            )
        )

        convert_translation = op.convert_translation
        def transform_translation(t): return mul(trans_mat, convert_translation(t))

        # In order to transform the tangents for cubic interpolation, we need to
        # know how the derivative transforms too. The other transforms are
        # linear, so their derivatives change the same way they do, but
        # transform_translation is affine, so its derivative changes by its
        # underlying linear map.
        lin_mat = trans_mat.to_3x3()
        def transform_velocity(t): return mul(lin_mat, convert_translation(t))

    if 'rotation' in samplers:
        # pt = er^{-1} cr(pb)^{-1} r cr(b)
        #    = left_r r cr(b)
        left_r = mul(er_inv, cr_pb_inv)

        convert_rotation = op.convert_rotation
        def transform_rotation(r): return mul(mul(left_r, convert_rotation(r)), cr)

    if 'scale' in samplers:
        # ps = (M cs(b) / cs(pb)) s
        # where M is the matrix from exchange_scale_rot_matrix
        scale_mat = exchange_scale_rot_matrix(bone_vnode.correction_rotation)
        scale_mat *= cs * cs_pb_inv

        convert_scale = op.convert_scale
        def transform_scale(s):
            return mul(scale_mat, convert_scale(s))

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


def exchange_scale_rot_matrix(r):
    """
    Gives a matrix M, depending on quaternion r, with the property that

        Scale[s] Rot[r] = Rot[r] Scale[Ms]

    for all s.

    In order for this to work, Rot[r] must be, up to sign, a permutation of the
    basis vectors.
    """
    # M should be the matrix for the inverse of the permutation effected by
    # Rot[r] I think.
    m = r.to_matrix()
    # Drop all signs; after this, M should be a permutation matrix
    for i in range(0, 3):
        for j in range(0, 3):
            m[i][j] = 0 if abs(m[i][j]) < 0.5 else 1
    m.transpose()
    return m
