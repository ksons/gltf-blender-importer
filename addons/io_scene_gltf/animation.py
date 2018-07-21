import json

import bpy
from mathutils import Vector, Quaternion, Matrix


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
    #     for each affected node_id: {
    #         'translation': {
    #             'input': [0.0, 0.1, 0.2, ...], # time
    #             'output': [[1, 0, 0], [2, 0, 0], ...], # translations
    #             'interpolation': 'LINEAR'
    #         },
    #         'rotation': ...,
    #         'scale': ...
    #     }
    # }
    node_curves = {}

    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']
        if 'node' not in target:
            continue
        node_id = target['node']
        path = target['path']

        input = op.get('accessor', sampler['input'])
        output = op.get('accessor', sampler['output'])
        interpolation = sampler.get('interpolation', 'LINEAR')

        if interpolation == 'CUBICSPLINE':
            # TODO: not supported; for now drop the tangents and switch to LINEAR
            # TODO: this work-around is also UNTESTED :)
            output = [output[i] for i in range(1, len(output, 3))]
            bl_interpolation = 'LINEAR'
        elif interpolation == 'STEP':
            bl_interpolation = 'CONSTANT'
        elif interpolation == 'LINEAR':
            bl_interpolation = 'LINEAR'
        else:
            print('unknown interpolation: %s', interpolation)
            bl_interpolation = 'LINEAR'


        node_curves.setdefault(node_id, {})[path] = {
            'input': input,
            'output': output,
            'interpolation': interpolation,
            'bl_interpolation': bl_interpolation,
        }

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

            ordinates = curve['output']
            if target == 'rotation' and curve['interpolation'] == 'LINEAR':
                ordinates = shorten_quaternion_paths(ordinates)

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
                fcurve.keyframe_points.add(len(curve['input']))

            for k, (t, y) in enumerate(zip(curve['input'], ordinates)):
                frame = t * op.framerate
                y = convert(y)
                for i, fcurve in enumerate(fcurves):
                    fcurve.keyframe_points[k].interpolation = curve['bl_interpolation']
                    fcurve.keyframe_points[k].co = [frame, y[i]]

            for fcurve in fcurves:
                fcurve.update()



def add_bone_fcurves(op, anim_id, node_id, curves):
    # Unlike an object, a bone doens't get its own action; there is one action
    # for the whole armature. To handle this, we store a cache of the action for
    # each animation in the armature's vnode and create one when we first
    # animate a bone in that armature.
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
    # So we need to compute a value for pose_trs that gives the specified final
    # position.
    #
    #    pose_trs = rest_trs^{-1} * final_trs
    #             = (rt rr)^{-1} (ft fr fs)   [assuming rest scale is 1]
    #             = rr^{-1} (-rt) ft fr fs
    #             = (rr^{-1} (-rt)) rr^{-1} ft fr fs
    #             = (rr^{-1} (-rt + ft)) rr^{-1} fr fs
    #             = (        pt        ) (   pr   ) ps
    #
    #
    # To this is added the consideration that we allow the user to choose a
    # rotation for bones (to allow them to get them to point in the "natural"
    # way for Blender), hence both the rest_trs and the final_trs and
    # premultiplied by the bone rotation, q. (TODO: check this paragraph??)

    t, r, s = bone_vnode['trs']
    q = op.bone_rotation.to_quaternion()
    r = r * q
    rest_trs = (t, r, s)

    # Here we only compute the ordinates of the new pose curves. The time
    # domains are the same as for the final curves.
    inverse_rest_rot = rest_trs[1].conjugated()
    pose_ordinates = {}
    if 'translation' in curves:
        inverse_rest_rot_mat = inverse_rest_rot.to_matrix()
        pose_ordinates['translation'] = [
            inverse_rest_rot_mat * (-rest_trs[0] + convert_translation(ft))
            for ft in curves['translation']['output']
        ]
    if 'rotation' in curves:
        pose_ordinates['rotation'] = [
            inverse_rest_rot * convert_rotation(fr) * q
            for fr in curves['rotation']['output']
        ]
    if 'scale' in curves:
        # TODO: we probably need some correction when the scaling is non-uniform
        # and q is not 1
        pose_ordinates['scale'] = [
            convert_scale(fs) for fs in curves['scale']['output']
        ]

    bone_name = bone_vnode['blender_name']
    base_path = 'pose.bones[%s]' % quote(bone_name)

    triples = [
        # (glTF path name, Blender path name, number of components)
        ('translation', 'location', 3),
        ('rotation', 'rotation_quaternion', 4),
        ('scale', 'scale', 3)
    ]
    for target, data_path, num_components in triples:
        if target in curves:
            curve = curves[target]
            ordinates = pose_ordinates[target]

            if target == 'rotation' and curve['interpolation'] == 'LINEAR':
                ordinates = shorten_quaternion_paths(ordinates)

            fcurves = [
                action.fcurves.new(data_path=base_path + '.' + data_path, index=i)
                for i in range(0, num_components)
            ]

            for fcurve in fcurves:
                fcurve.keyframe_points.add(len(curve['input']))

            for k, (t, y) in enumerate(zip(curve['input'], ordinates)):
                frame = t * op.framerate
                for i, fcurve in enumerate(fcurves):
                    fcurve.keyframe_points[k].interpolation = curve['bl_interpolation']
                    fcurve.keyframe_points[k].co = [frame, y[i]]

            for fcurve in fcurves:
                fcurve.update()


def shorten_quaternion_paths(qs):
    """
    Given a list of quaternions, return a list of quaternions which produce the
    same rotations but where each element is always the closest quaternion to
    its predecessor.

    Applying this to the ordinates of a curve ensure rotation always takes the
    "shortest path". See glTF issue #1395.
    """
    # Also note: it does not matter if you apply this before or after coordinate
    # conversion :)
    res = []
    if qs: res.append(qs[0])
    for i in range(1, len(qs)):
        q = Quaternion(qs[i])
        res.append(-q if q.dot(res[-1]) < 0 else q)
    return res
