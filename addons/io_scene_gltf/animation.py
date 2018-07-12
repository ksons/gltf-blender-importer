import json

import bpy
from mathutils import Vector, Quaternion, Matrix


# Throughout this file, a "curve" is a map from domain points to ordinates,
# represented as either a pair of lists, (domain_points, ordinates), which is how
# they naturally come out of a glTF, or as a list of (domain_point, ordinate)
# pairs, which is easier to consume for Blender.
#
# All curves we use are extended to intermediate domain points by linear
# interpolation.

# An animation targets some quantity in a scene and says that it varies over
# time by giving a curve mapping the time to the value of that quantity at that
# time.


# Quotes a string using double-quotes (used for Blender data paths).
def quote(s): return json.dumps(s)

# These functions convert from glTF conventions to Blender
def convert_translation(t):
    return Vector([t[0], -t[2], t[1]])
def convert_rotation(r):
    r = [r[3], r[0], r[1], r[2]]
    return Quaternion([r[0], r[1], -r[3], r[2]])
def convert_scale(s):
    return Vector([s[0], s[2], s[1]])

CONVERT_FNS = {
    'translation': convert_translation,
    'rotation': convert_rotation,
    'scale': convert_scale,
}



def add_animations(op):
    """Adds all the animations in the glTF file to Blender."""
    for i in range(0, len(op.gltf.get('animations', []))):
        add_animation(op, i)


def add_animation(op, anim_id):
    """Adds the animation with the given index to Blender."""
    anim = op.gltf['animations'][anim_id]
    channels = anim['channels']
    samplers = anim['samplers']

    # Gather all the curves that affect a given node. node_curves will look like
    # {
    #     node_id: {
    #         'translation': (
    #             [0.0, 0.1, 0.2, ...], # inputs
    #             [[1.0, 0.0, 0.0], [1.2, 0.0, 0.0], ...], # outputs
    #         )
    #         'rotation': ...,
    #         ...
    #     }
    #     ...
    # }
    node_curves = {}

    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']
        if 'node' not in target:
            continue
        node_id = target['node']
        path = target['path']

        node_curves.setdefault(node_id, {})[path] = (
            op.get('accessor', sampler['input']),
            op.get('accessor', sampler['output']),
        )

    for node_id, curves in node_curves.items():
        if op.id_to_vnode[node_id]['type'] == 'BONE':
            add_bone_fcurves(op, anim_id, node_id, curves)
        else:
            add_action(op, anim_id, node_id, curves)




def add_action(op, animation_id, node_id, curves):
    # An action in Blender contains fcurves (Blender's animation curves) which
    # target a particular TRS component. An action only applies to one object,
    # so we need to create an action for each (glTF animation, animated object)
    # pair. This is unfortunate; it would be better to
    animation = op.gltf['animations'][animation_id]
    name = animation.get('name', 'animations[%d]' % animation_id)
    blender_object = op.id_to_vnode[node_id]['blender_object']
    name += '@' + blender_object.name

    action = bpy.data.actions.new(name)

    if blender_object.animation_data is None:
        blender_object.animation_data_create().action = action

    # The values in the glTF curve are the same (excepting the change of
    # coordinates) as those needed in Blender's fcurve so we just copy them on
    # through.

    triples = [
        # (glTF path name, Blender path name, number of components)
        ('translation', 'location', 3),
        ('rotation', 'rotation_quaternion', 4),
        ('scale', 'scale', 3)
    ]
    for target, data_path, num_components in triples:
        if target in curves:
            curve = curves[target]
            convert = CONVERT_FNS[target]

            # Create an fcurve for each component (eg. xyz) and then loop over
            # the curve's points, filling in each fcurve with the corresponding
            # component.
            #
            # NOTE: using keyframe_points.add/keyframe_points[k].co is *much*
            # faster than using keyframe_points.insert.

            fcurves = [
                action.fcurves.new(data_path=data_path, index=i)
                for i in range(0, num_components)
            ]

            for fcurve in fcurves:
                fcurve.keyframe_points.add(len(curve[0]))

            for k, (t, y) in enumerate(zip(curve[0], curve[1])):
                frame = t * op.framerate
                y = convert(y)
                for i, fcurve in enumerate(fcurves):
                    fcurve.keyframe_points[k].co = [frame, y[i]]

            for fcurve in fcurves:
                fcurve.update()



def add_bone_fcurves(op, anim_id, node_id, curves):
    # When a bone is the target of a curve, things are more complicated. The values
    # in the gLTF curve are not the values we need for the fcurves so we need to do
    # some computation to find the correct values before we create the fcurves.


    # To start with, unlike an object, a bone doens't get its own action; there
    # is one action for the whole armature. To handle this, we store a cache of
    # the action for each animation in the armature's vnode and create one when
    # we first animate a bone in that armature.
    bone_vnode = op.id_to_vnode[node_id]
    armature_vnode = bone_vnode['armature_vnode']
    action_cache = armature_vnode.setdefault('action_cache', {})
    if anim_id not in action_cache:
        name = op.gltf['animations'][anim_id].get('name', 'animations[%d]' % anim_id)
        name += '@' + armature_vnode['blender_armature'].name
        action = bpy.data.actions.new(name)
        action_cache[anim_id] = bpy.data.actions.new(name)
        if armature_vnode['blender_armature'].animation_data is None:
            armature_vnode['blender_armature'].animation_data_create().action = action

    action = action_cache[anim_id]


    rest_trs = bone_vnode['trs']

    # In glTF, the ordinates of an animation curve say what the final position
    # of the node should be
    #
    #    final_trs = sample_gltf_curve()
    #
    # But in Blender, when handling bones, you don't animate the bone directly
    # like this, you animate a "pose bone", and the final position is computed
    # as
    #
    #    pose_trs = sample_blender_fcurve()
    #    final_trs = rest_trs * pose_trs
    #
    # (TODO: is that order of multiplication correct?)
    #
    # So we need to compute a value for pose_trs that gives the specified final
    # position.
    #
    #    pose_trs = rest_trs^{-1} * final_trs
    #
    # However, to do this computation we need a whole TRS for each of these
    # values; the curves in the glTF give only one piece, say the T piece at
    # once. So we need to put the curves together to get a (time) -> (final_trs)
    # curve. But the curves may be sampled at different rates, eg. the
    # translation curve might be sampled at times
    #
    #    0.0, 0.2, 0.4, 0.6, 0.8, ...
    #
    # while the rotation curve is sampled at times
    #
    #    0.1, 0.3, 0.4, 0.5, 0.55, 1.1, ...
    #
    # so in order to get a single curve we need to have a common domain, so we
    # first need to resample the individual curves onto their common domain, eg.
    # in the above case
    #
    #    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.8, 1.1, ...
    #
    # Once we've done this we have a (time) -> (final_trs) curve and we can
    # compute the (time) -> (pose_trs) curve, project it into its ten components
    # to get ten curves, and these are the fcurves Blender requires.

    pose_trs_curves = build_pose_trs_curves(op, curves, rest_trs)

    # pose_trs_curves is a list of ten (time) -> (final_trs component) curves,
    # in the list of pairs representation. (Actually, they're (frame) ->
    # (final_trs component) curves.) We just need to copy them into fcurves now.

    bone_name = bone_vnode['blender_name']
    base_path = 'pose.bones[%s]' % quote(bone_name)

    # Default value of each of the 10 TRS component
    defaults = [
        0, 0, 0,
        1, 0, 0, 0,
        1, 1, 1,
    ]
    # Index of each of the 10 components into its containing T, R, or S component
    indices = [
        0, 1, 2,
        0, 1, 2, 3,
        0, 1, 2,
    ]
    # The Blender path for each of the 10 components
    paths = [
        'location', 'location', 'location',
        'rotation_quaternion', 'rotation_quaternion', 'rotation_quaternion', 'rotation_quaternion',
        'scale', 'scale', 'scale',
    ]
    for i, pose_trs_curve in enumerate(pose_trs_curves):
        # We'll do one final step before writing an fcurve.
        #
        # Note that even if the eg. scale component of the final_trs isn't
        # animated, the scale component of the pose_trs might be so we did need
        # to pass everything through a component -> whole TRS -> components
        # pipe.
        #
        # However, although that can happen, many of the resulting (time) ->
        # (pose_TRS component) curves are superfluous -- they are constantly the
        # default value for that component (eg. the X-scale curve might be
        # constantly 1) -- or they contain superfluous points, which would
        # result from lerping their neighbors.
        #
        #    . a
        #     \
        #      .    <- superfluous point (results from lerping a and b)
        #       \
        #        . b
        #
        # We'll attempt to clean-up the new curves we've generated by removing
        # these curves and points before we insert them into the fcurves.
        #
        # Obviously, this step is not necessary.

        cleanup_curve(pose_trs_curve)

        # Check if the whole curve is superfluous (constantly its default value)
        if (
            len(pose_trs_curve) == 2 and
            approx_eq(pose_trs_curve[0][1], defaults[i]) and
            approx_eq(pose_trs_curve[0][1], pose_trs_curve[1][1])
        ):
            continue

        # Copy the curve into an fcurve

        data_path = base_path + '.' + paths[i]
        fcurve = action.fcurves.new(data_path=data_path, index=indices[i])
        fcurve.keyframe_points.add(len(pose_trs_curve))

        for i, co in enumerate(pose_trs_curve):
            fcurve.keyframe_points[i].co = co

        fcurve.update()


def mul_trs(trs2, trs1):
    """Compute the composition of trs2 following trs1."""
    # TODO: this is not correct for non-uniform scalings

    t1 = trs1[0]
    t2 = trs2[0]
    r1 = trs1[1]
    r2 = trs2[1]
    s1 = trs1[2]
    s2 = trs2[2]

    t3 = t2 + r2.to_matrix() * Vector([s2[0]*t1[0], s2[1]*t1[1], s2[2]*t1[2]])
    r3 = r2 * r1
    s3 = [s1[i] * s2[i] for i in range(0,3)]

    return (t3, r3, s3)

def invert_trs(trs):
    # TODO: also not right for non-uniform scalings
    si = [1.0 / trs[2][i] for i in range(0,3)]
    ri = trs[1].conjugated()
    ti = Vector(trs[0])
    ti[0] *= si[0]
    ti[1] *= si[1]
    ti[2] *= si[2]
    ti = - (ri.to_matrix() * ti)
    return (ti, ri, si)



def build_pose_trs_curves(op, curves, rest_trs):
    # This function takes as input a map sending the name of TRS pieces eg.
    # 'translation' to the glTF curve for that piece, (time) -> (final_trs
    # piece), in the pair of lists representation.
    #
    # It returns a list of ten (frame) -> (pose_trs component) curves in the
    # list of pairs representation.
    #
    # It actually does several jobs:
    #
    # 1. resamples the input curves onto the union of their domains
    # 2. fills in any missing curves with the value from the rest_trs to get the
    #    final_trs
    # 3. computes the pose_trs from the final_trs
    # 4. projects the final_trs onto its ten component curves
    # 5. converts from the time domain to the frame domain
    #
    # (The reason for doing all this in one function instead of a pipeline of
    # simpler functions is to avoid creating large intermediate results.)

    # We'll address the different paths by indices 0-3 instead of by name in
    # this function.
    curves = [
        curves.get('translation', ([], [])),
        curves.get('rotation', ([], [])),
        curves.get('scale', ([], [])),
    ]
    convert_fns = [
        convert_translation,
        convert_rotation,
        convert_scale,
    ]

    # Since the domains are sorted, we can process the curves in order. index[i]
    # is the index of the first point in curves[i] that we haven't sampled yet.
    index = [0, 0, 0]

    inv_rest_trs = invert_trs(rest_trs)

    trs_curves = [[], [], [], [], [], [], [], [], [], []]

    while True:
        # Find the smallest domain point we haven't sampled yet.
        t = min((curves[i][0][index[i]]
            for i in range(0, 3)
            if index[i] < len(curves[i][0])
        ), default=None)
        if t == None:
            # Done!
            break

        final_trs = []

        for i, curve in enumerate(curves):
            inputs = curve[0]
            outputs = curve[1]
            convert = convert_fns[i]

            if len(inputs) == 0:
                val = rest_trs[i]
            else:
                if t < inputs[0]:
                    val = outputs[0]
                elif t > inputs[-1] or index[i] == len(inputs):
                    val = outputs[-1]
                elif t == inputs[index[i]]:
                    val = outputs[index[i]]
                    index[i] += 1
                else:
                    # Lerp between the nearest two points
                    if inputs[index[i]-1] < t < inputs[index[i]]:
                        left = index[i] - 1
                    elif inputs[index[i]] < t < inputs[index[i]+1]:
                        left = index[i]
                    else:
                        assert(False)
                    right = left + 1
                    lam = (t - inputs[left]) / (inputs[right] - inputs[left])
                    val = (1 - lam) * Vector(outputs[left]) + lam * Vector(outputs[right])
                val = convert(val)

            final_trs.append(val)

        pose_trs = mul_trs(inv_rest_trs, final_trs)

        frame = t * op.framerate
        trs_curves[0].append([frame, pose_trs[0][0]])
        trs_curves[1].append([frame, pose_trs[0][1]])
        trs_curves[2].append([frame, pose_trs[0][2]])
        trs_curves[3].append([frame, pose_trs[1][0]])
        trs_curves[4].append([frame, pose_trs[1][1]])
        trs_curves[5].append([frame, pose_trs[1][2]])
        trs_curves[6].append([frame, pose_trs[1][3]])
        trs_curves[7].append([frame, pose_trs[2][0]])
        trs_curves[8].append([frame, pose_trs[2][1]])
        trs_curves[9].append([frame, pose_trs[2][2]])

    return trs_curves


def approx_eq(x, y):
    return abs(x - y) < 0.00001


def cleanup_curve(curve):
    """Removes superfluous points from a curve in list of pairs representation.

    A point is superfluous if it would result from lerping its neighbors and so
    has no need to be stored.
    """

    i = 1
    while i < len(curve) - 1:
        lam = (curve[i][0] - curve[i-1][0]) / (curve[i+1][0] - curve[i-1][0])
        lerp = (1 - lam) * curve[i-1][1] + lam * curve[i+1][1]
        if approx_eq(lerp, curve[i][1]):
            del curve[i]
            continue

        i += 1
