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
    #         'scale': ...,
    #         'weights': ...,
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
        if 'weights' in curves:
            add_shape_key_action(op, anim_id, node_id, curves['weights'])




def add_action(op, animation_id, node_id, curves):
    # An action in Blender contains fcurves (Blender's animation curves) which
    # target a particular TRS component. An action only applies to one object,
    # so we need to create an action for each (glTF animation, animated object)
    # pair. This is unfortunate; it would be better to have a one-to-one
    # correspondence glTF animation <-> Blender ???.
    animation = op.gltf['animations'][animation_id]
    name = animation.get('name', 'animations[%d]' % animation_id)
    blender_object = op.id_to_vnode[node_id]['blender_object']
    name += '@' + blender_object.name

    action = bpy.data.actions.new(name)
    action.use_fake_user = True

    # Play the first animation by default
    if animation_id == 0:
        blender_object.animation_data_create().action = action

    # The values in the glTF curve are the same (excepting the change of
    # coordinates) as those needed in Blender's fcurve so we just copy them on
    # through.

    target_data = [
        # (glTF path name, Blender path name, group name, number of components)
        ('translation', 'location', 'Location', 3),
        ('rotation', 'rotation_quaternion', 'Rotation', 4),
        ('scale', 'scale', 'Scale', 3)
    ]
    for target, data_path, group_name, num_components in target_data:
        if target in curves:
            curve = curves[target]
            convert = CONVERT_FNS[target]


            ordinates = curve['output']
            if target == 'rotation' and curve['interpolation'] == 'LINEAR':
                ordinates = shorten_quaternion_paths(ordinates)

            group = action.groups.new(group_name)

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
                fcurve.group = group

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
        action_cache[anim_id] = action
        action.use_fake_user = True

        # Play the first animation by default
        if anim_id == 0:
            bl_object = armature_vnode['blender_object']
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
    # changed and they are still independant and don't need to be resampled.

    et, er = bone_vnode['bone_tr']
    ier, iet = er.conjugated(), -et
    parent_pre_r = bone_vnode['parent'].get('bone_pre_rotation', Quaternion((1,0,0,0)))
    post_r = parent_pre_r.conjugated()
    pre_r = bone_vnode.get('bone_pre_rotation', Quaternion((1,0,0,0)))
    parent_pre_s = bone_vnode['parent'].get('bone_pre_scale', Vector((1,1,1)))
    post_s = Vector((1/c for c in parent_pre_s))
    pre_s = bone_vnode.get('bone_pre_scale', Vector((1,1,1)))

    pose_ordinates = {}
    if 'translation' in curves:
        # pt = Rot[er^{-1}](-et) + Rot[er^{-1}] Scale[post_s] Rot[post_r] t
        #    = c + m t
        ier_mat = ier.to_matrix().to_4x4()
        post_s_mat = Matrix.Identity(4)
        for i in range(0, 3): post_s_mat[i][i] = post_s[i]
        c = ier_mat * iet
        m = ier_mat * post_s_mat * post_r.to_matrix().to_4x4()

        pose_ordinates['translation'] = [
            c + m * convert_translation(t)
            for t in curves['translation']['output']
        ]
    if 'rotation' in curves:
        # pt = er^{-1} * post_r * r * pre_r
        #    = c * r * pre_r
        c = ier * post_r
        pose_ordinates['rotation'] = [
            c * convert_rotation(r) * pre_r
            for r in curves['rotation']['output']
        ]
    if 'scale' in curves:
        # ps = post_s * s' * pre_s
        perm = bone_vnode['bone_pre_perm']
        def permute(s):
            return Vector((s[perm[0]], s[perm[1]], s[perm[2]]))
        def mul(s):
            return Vector((post_s[i] * s[i] * pre_s[i] for i in range(0,3)))
        pose_ordinates['scale'] = [
            mul(permute(convert_scale(s)))
            for s in curves['scale']['output']
        ]


    bone_name = bone_vnode['blender_name']
    base_path = 'pose.bones[%s]' % quote(bone_name)

    group = action.groups.new(bone_name)

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
                fcurve.group = group

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



def add_shape_key_action(op, anim_id, node_id, curve):
    # We have to create a separate action for animating shape keys.
    animation = op.gltf['animations'][anim_id]
    vnode = op.id_to_vnode[node_id]
    if 'mesh_instance_moved_to' in vnode:
        vnode = vnode['mesh_instance_moved_to']
    blender_object = vnode['blender_object']

    if not blender_object.data.shape_keys:
        # Can happen if the mesh has only non-POSITION morph targets so we
        # didn't create a shape key
        return

    name = animation.get('name', 'animations[%d]' % anim_id)
    name += '@' + blender_object.name
    name += ' (Morph)'
    action = bpy.data.actions.new(name)
    action.id_root = 'KEY'
    action.use_fake_user = True

    # Play the first animation by default
    if anim_id == 0:
        blender_object.data.shape_keys.animation_data_create().action = action

    # Find out the number of morph targets
    mesh = op.gltf['meshes'][op.gltf['nodes'][node_id]['mesh']]
    num_targets = len(mesh['primitives'][0]['targets'])

    for i in range(0, num_targets):
        data_path = 'key_blocks[%s].value' % quote('Morph %d' % i)
        fcurve = action.fcurves.new(data_path=data_path)
        fcurve.keyframe_points.add(len(curve['input']))

        for k, t in enumerate(curve['input']):
            frame = t * op.framerate
            y = curve['output'][num_targets * k + i]
            fcurve.keyframe_points[k].interpolation = curve['bl_interpolation']
            fcurve.keyframe_points[k].co = [frame, y]

        fcurve.update()
