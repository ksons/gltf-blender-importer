import bpy
import json
from mathutils import Vector, Quaternion, Matrix

# Scale sampler input ("time") by this to get the frame of the
# animation.
#TODO think more about this?
FRAME_RATE = 60

def quote(s): return json.dumps(s)


def add_animations(op):
    for i in range(0, len(op.gltf.get('animations', []))):
        add_animation(op, i)


def add_animation(op, anim_id):
    anim = op.gltf['animations'][anim_id]
    name = anim.get('name', 'animations[%d]' % anim_id)
    channels = anim['channels']
    samplers = anim['samplers']

    # Gather all the samplers that affect a given node
    node_curves = {}

    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']
        if 'node' not in target:
            continue
        node_id = target['node']
        path = target['path']

        node_curves.setdefault(node_id, {})[path] = {
            'input': op.get('accessor', sampler['input']),
            'output': op.get('accessor', sampler['output']),
        }

    for node_id, curves in node_curves.items():
        if op.id_to_vnode[node_id]['type'] == 'BONE':
            compute_bone_fcurves(op, anim_id, node_id, curves)
        else:
            add_actions(op, anim_id, node_id, curves)


def add_actions(op, animation_id, node_id, curves):
    animation = op.gltf['animations'][animation_id]
    name = animation.get('name', 'animation[%d]' % animation_id)
    blender_object = op.id_to_vnode[node_id]['blender_object']
    name += '@' + blender_object.name

    action = bpy.data.actions.new(name)
    blender_object.animation_data_create().action = action

    name = op.id_to_vnode[node_id]['blender_object'].name

    if 'translation' in curves:
        curve = curves['translation']
        for i in range(0, 3):
            fcurve = action.fcurves.new(data_path='location', index=i)
            for t, y in zip(curve['input'], curve['output']):
                y = [y[0], -y[2], y[1]] # convert to Blender coordinates
                fcurve.keyframe_points.insert(FRAME_RATE * t, y[i])
            fcurve.update()

    if 'rotation' in curves:
        curve = curves['rotation']
        for i in range(0, 4):
            fcurve = action.fcurves.new(data_path='rotation_quaternion', index=i)
            for t, y in zip(curve['input'], curve['output']):
                y = [y[0], y[1], -y[3], y[2]] # convert to Blender coordinates
                fcurve.keyframe_points.insert(FRAME_RATE * t, y[i])
            fcurve.update()

    if 'scale' in curves:
        curve = curves['scale']
        for i in range(0, 3):
            fcurve = action.fcurves.new(data_path='scale', index=i)
            for t, y in zip(curve['input'], curve['output']):
                y = [y[0], y[2], y[1]] # convert to Blender coordinates
                fcurve.keyframe_points.insert(FRAME_RATE * t, y[i])
            fcurve.update()


# TODO: this comment was for a WIP version and doesn't reflect the code below
# exactly.
#
# Importing animations that target nodes that in Blender are represented by
# bones is more complicated.
#
# In glTF, the animation curves specify the positions of a node at a given time
# directly. _animation_curve()
#
# In Blender, the animation curves specify the positions of the pose bones, and
# the positions of the nodes are calculat final_position = sampleed by
# post-composing the positions of the pose bones to the positions of the rest
# bones
#
#     pose_position = sample_animation_curve()
#     final_position = pose_position * rest_position
#
# Therefore we need to compute appropriate TRSes for the pose positions to give
# to Blender from the desired final positions stored in the glTF file by
#
#     pose_position = final_position * rest_position^{-1}
#
# This raises another issue. In both glTF and Blender, the animation curves do
# not map time to the whole TRS value, but to one of the TRS components (in
# glTF, to one of translation, rotation, or scale; in Blender, to one of the 10
# individual numbers in the TRS). In order to carry out the above calculation,
# we need a curve mapping time to the TRS. But we before we can stick the
# individual curves together they need to resampled onto a common domain, eg:
# the translation curve might have domain
#
#     0.0, 0.1, 0.5, 0.9, 1.1, ...
#
# while the rotations curve has domain
#
#     0.0, 0.2, 0.4, 0.6, 0.8, 1.0, ...
#
# So we need to resample the curves onto their common domain
#
#     0.0, 0.1, 0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 1.0, 1.1, ...
#
# before we can compute the pose position.
#
# This gives a time -> TRS curve and we can easily project in into the ten time
# -> (real number) curves for each TRS property that correctly animates the
# Blender armature. However, many of these curves may contain superfluous points
# -- points whose ordinate is the (approximate) lerp of its neighbors and can be
# deleted without affecting the curve's value
#
#    . a
#     \
#      .    <- superfluous point (results from lerping a and b)
#       \
#        . b
#
# -- or else the curve itself may be entirely superfluous -- when it is an
# (approximate) constant whose value is the default for the component (eg. when
# it is constantly 1.0 for a scale component) and the whole curve can be deleted
# without affecting the animation.
#
# Therefore the whole process of importing an animation targeting a joint/bone
# is
#
# 1. gather the glTF curves that target the joint
# 2. resample them onto a common domain to compute a time -> (final TRS) curve
# 3. compute pose positions, giving a time -> (pose TRS) curve
# 4. split into 10 time -> (real number) curves, and
# 5. clean-up superfluous points and curves


def compute_bone_fcurves(op, anim_id, node_id, curves):
    bone_vnode = op.id_to_vnode[node_id]
    armature_vnode = bone_vnode['armature_vnode']
    action_cache = armature_vnode.setdefault('action_cache', {})
    if anim_id not in action_cache:
        name = op.gltf['animations'][anim_id].get('name', 'animations[%d]' % anim_id)
        name += '@' + armature_vnode['blender_armature'].name
        action = bpy.data.actions.new(name)
        action_cache[anim_id] = bpy.data.actions.new(name)
        armature_vnode['blender_armature'].animation_data_create().action = action

    action = action_cache[anim_id]

    bone_name = bone_vnode['blender_name']
    base_path = 'pose.bones[%s]' % quote(bone_name)

    rest_trans = Vector(bone_vnode['trs'][0])
    rest_rot = Quaternion(bone_vnode['trs'][1])
    rest_scale = Vector(bone_vnode['trs'][2])
    defaults = {
        'translation': rest_trans,
        'rotation': rest_rot,
        'scale': rest_scale,
    }

    si = [1.0 / rest_scale[i] for i in range(0,3)]
    ri = rest_rot.conjugated()
    ti = Vector(rest_trans)
    ti[0] *= si[0]
    ti[1] *= si[1]
    ti[2] *= si[2]
    ti = - (ri.to_matrix() * ti)
    inv_rest = (ti, ri, si)

    trs_curve = resample_onto_common_domain(curves, defaults)

    times = trs_curve['input']
    trses = trs_curve['output']
    for i in range(0, len(trses)):
        trses[i][1].normalize()
        trses[i] = mul_trs(inv_rest, trses[i])

    for i in range(0, 3):
        data_path = base_path + '.location'
        fcurve = action.fcurves.new(data_path=data_path, index=i)
        for t, y in zip(times, trses):
            fcurve.keyframe_points.insert(FRAME_RATE * t, y[0][i])
        fcurve.update()

    for i in range(0, 4):
        data_path = base_path + '.rotation_quaternion'
        fcurve = action.fcurves.new(data_path=data_path, index=i)
        for t, y in zip(times, trses):
            fcurve.keyframe_points.insert(FRAME_RATE * t, y[1][i])
        fcurve.update()

    for i in range(0,3):
        data_path = base_path + '.scale'
        fcurve = action.fcurves.new(data_path=data_path, index=i)
        for t, y in zip(times, trses):
            fcurve.keyframe_points.insert(FRAME_RATE * t, y[2][i])
        fcurve.update()


def trs_to_mat(trs):
    m = Matrix.Translation(trs[0])
    m = trs[1].to_matrix().to_4x4() * m
    sm = Matrix.Identity(4)
    for i in range(0,3): sm[i][i] = trs[2][i]
    return sm * m

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




def convert_translation(t): return Vector([t[0], -t[2], t[1]])
def convert_rotation(r):
    r = [r[3], r[0], r[1], r[2]]
    return Quaternion([r[0], r[1], -r[3], r[2]])
def convert_scale(s): return Vector([s[0], s[2], s[1]])

def resample_onto_common_domain(curves, defaults):
    index = {}
    for target in curves.keys(): index[target] = 0

    fetch_fns = {
        'translation': convert_translation,
        'rotation': convert_rotation,
        'scale': convert_scale,
    }

    domain = []
    ordinates = []

    while True:
        # Find the next smallest domain value
        t = min((curves[key]['input'][index[key]]
            for key in curves.keys()
            if index[key] < len(curves[key]['input'])
        ), default=None)
        if t == None:
            # Done!
            break

        domain.append(t)

        ord = []

        for target in ['translation', 'rotation', 'scale']:
            if target not in index:
                ord.append(defaults[target])
                continue

            curve = curves[target]
            input = curve['input']
            output = curve['output']
            fetch = fetch_fns[target]

            if t < input[0]:
                ord.append(fetch(output[0]))
                continue

            if t > input[-1] or index[target] == len(input):
                ord.append(fetch(output[-1]))
                continue

            if t == input[index[target]]:
                ord.append(fetch(output[index[target]]))
                index[target] += 1
                continue

            if input[index[target]-1] < t < input[index[target]]:
                left = index[target] - 1
            elif input[index[target]] < t < input[index[target] + 1]:
                left = index[target]
            else:
                assert(False)
            right = left + 1

            lam = (t - input[left]) / (input[right] - input[left])
            lerp = (1 - lam) * fetch(output[left]) + lam * fetch(output[right])
            ord.append(lerp)

        ordinates.append(tuple(ord))

    return { 'input': domain, 'output': ordinates }


def approx_eq(x, y):
    return abs(x - y) < 0.0001


def remove_superfluous_points(curve):
    """Removes superfluous points from a curve.

    A point is superfluous if it would result from lerping its neighbors and so
    has no need to be stored.
    """

    i = 1
    while i < len(curve[0]) - 1:
        lam = (curve[0][i] - curve[0][i-1]) / (curve[0][i+1] - curve[0][i-1])
        lerp = (1 - lam) * curve[1][i-1] + lam * curve[1][i+1]
        if approx_eq(lerp, curve[1][i]):
            del curve[0][i]
            del curve[1][i]
            continue

        i += 1
