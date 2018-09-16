import json, re

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


# As a first step towards importing, re-organize the data in a glTF animation
# around what kind of thing is being animated (a node or a material), which
# thing is being animated (the ID of the node or material), and which property
# of that thing is being animated (translation, base color factor, etc).
#
# The re-organized data is stored in op.animation_info.
def gather_animations(op):
    op.animation_info = []
    for anim_id in range(0, len(op.gltf.get('animations', []))):
        op.animation_info.append(gather_animation(op, anim_id))

def read_sampler(op, sampler):
    input = op.get('accessor', sampler['input'])
    output = op.get('accessor', sampler['output'])
    interpolation = sampler.get('interpolation', 'LINEAR')

    if interpolation == 'CUBICSPLINE':
        # TODO: not supported; for now drop the tangents and switch to LINEAR
        # TODO: this work-around is also UNTESTED :)
        output = [output[i] for i in range(1, len(output), 3)]
        bl_interpolation = 'LINEAR'
    elif interpolation == 'STEP':
        bl_interpolation = 'CONSTANT'
    elif interpolation == 'LINEAR':
        bl_interpolation = 'LINEAR'
    else:
        print('unknown interpolation: %s', interpolation)
        bl_interpolation = 'LINEAR'

    return {
        'input': input,
        'output': output,
        'interpolation': interpolation,
        'bl_interpolation': bl_interpolation,
    }

def gather_animation(op, anim_id):
    anim = op.gltf['animations'][anim_id]
    samplers = anim['samplers']

    node_curves = {}
    material_curves = {}

    channels = anim['channels']
    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']
        if 'node' not in target:
            continue
        node_id = target['node']
        path = target['path']
        if path not in ['translation', 'rotation', 'scale', 'weights']:
            print('skipping animation curve, unknown path: %s' % path)
            continue

        curve = read_sampler(op, sampler)
        node_curves.setdefault(node_id, {})[path] = curve

    # EXT_property_animation channels
    channels = anim.get('extensions', {}).get('EXT_property_animation', {}).get('channels', [])
    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']

        # Parse the target
        patterns = [
            r'/(nodes)/(\d+)/(translation|rotation|scale)',
            r'/(materials)/(\d+)/(emissiveFactor|alphaCutoff)$',
            r'/(materials)/(\d+)/(normalTexture/scale|occlusionTexture/strength)$',
            r'/(materials)/(\d+)/pbrMetallicRoughness/(baseColorFactor|metallicFactor|roughnessFactor)$',
            r'/(materials)/(\d+)/extensions/KHR_materials_pbrSpecularGlossiness/(diffuseFactor|specularFactor|glossinessFactor)$',
            # Next up is texture transform properties
        ]
        result = None
        for pattern in patterns:
            match = re.match(pattern, target)
            if match:
                result = list(match.groups())
                result[1] = int(result[1])
                break
        if not result:
            print('skipping animation curve, target not supported: %s' % target)
            continue

        curve = read_sampler(op, sampler)
        if result[0] == 'nodes':
            node_curves.setdefault(result[1], {})[result[2]] = curve
        elif result[0] == 'materials':
            material_curves.setdefault(result[1], {})[result[2]] = curve
        else:
            assert(False)

    return {
        'nodes': node_curves,
        'materials': material_curves,
    }


def add_animations(op):
    """Adds all the animations in the glTF file to Blender."""
    for i in range(0, len(op.gltf.get('animations', []))):
        add_animation(op, i)

def add_animation(op, anim_id):
    info = op.animation_info[anim_id]

    for node_id, curves in info['nodes'].items():
        if op.id_to_vnode[node_id]['type'] == 'BONE':
            add_bone_fcurves(op, anim_id, node_id, curves)
        else:
            add_action(op, anim_id, node_id, curves)

        if 'weights' in curves:
            add_shape_key_action(op, anim_id, node_id, curves['weights'])

    for material_id, curves in info['materials'].items():
        add_material_action(op, anim_id, material_id, curves)



def add_action(op, animation_id, node_id, curves):
    # An action in Blender contains fcurves (Blender's animation curves) which
    # target a particular TRS component. An action only applies to one object,
    # so we need to create an action for each (glTF animation, animated object)
    # pair. This is unfortunate; it would be better to have a one-to-one
    # correspondence glTF animation <-> Blender ???.
    animation = op.gltf['animations'][animation_id]
    blender_object = op.id_to_vnode[node_id]['blender_object']
    name = (
        animation.get('name', 'animations[%d]' % animation_id) +
        '@' +
        blender_object.name
    )
    action = bpy.data.actions.new(name)
    action.use_fake_user = True

    # Play the first animation by default
    if animation_id == 0:
        blender_object.animation_data_create().action = action


    if 'translation' in curves:
        curve = curves['translation']
        ordinates = (convert_translation(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 3, 'location'
        )
        group = action.groups.new('Location')
        for fcurve in fcurves:
            fcurve.group = group

    if 'rotation' in curves:
        curve = curves['rotation']
        if curve['interpolation'] == 'LINEAR':
            shortened = shorten_quaternion_paths(curve['output'])
            ordinates = (convert_rotation(o) for o in shortened)
        else:
            ordinates = (convert_rotation(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 4, 'rotation_quaternion'
        )
        group = action.groups.new('Rotation')
        for fcurve in fcurves:
            fcurve.group = group

    if 'scale' in curves:
        curve = curves['scale']
        ordinates = (convert_scale(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 3, 'scale'
        )
        group = action.groups.new('Scale')
        for fcurve in fcurves:
            fcurve.group = group



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

    if 'translation' in curves:
        # pt = Rot[er^{-1}](-et) + Rot[er^{-1}] Scale[post_s] Rot[post_r] t
        #    = c + m t
        ier_mat = ier.to_matrix().to_4x4()
        post_s_mat = Matrix.Identity(4)
        for i in range(0, 3): post_s_mat[i][i] = post_s[i]
        c = ier_mat * iet
        m = ier_mat * post_s_mat * post_r.to_matrix().to_4x4()

        def mod_translation(t): return c + m * convert_translation(t)

    if 'rotation' in curves:
        # pt = er^{-1} * post_r * r * pre_r
        #    = d * r * pre_r
        d = ier * post_r

        def mod_rotation(r): return d * convert_rotation(r) * pre_r

    if 'scale' in curves:
        # ps = post_s * s' * pre_s
        perm = bone_vnode['bone_pre_perm']

        def mod_scale(s):
            s = convert_scale(s)
            s = Vector((s[perm[0]], s[perm[1]], s[perm[2]]))
            return Vector((post_s[i] * s[i] * pre_s[i] for i in range(0,3)))


    bone_name = bone_vnode['blender_name']
    base_path = 'pose.bones[%s]' % quote(bone_name)

    group = action.groups.new(bone_name)

    if 'translation' in curves:
        curve = curves['translation']
        ordinates = (mod_translation(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 3, base_path+'.location'
        )
        for fcurve in fcurves:
            fcurve.group = group

    if 'rotation' in curves:
        curve = curves['rotation']
        if curve['interpolation'] == 'LINEAR':
            modified = [mod_rotation(o) for o in curve['output']]
            ordinates = shorten_quaternion_paths(modified)
        else:
            ordinates = (mod_rotation(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 4, base_path+'.rotation_quaternion'
        )
        for fcurve in fcurves:
            fcurve.group = group

    if 'scale' in curves:
        curve = curves['scale']
        ordinates = (mod_scale(o) for o in curve['output'])
        fcurves = add_fcurves(
            op, action, curve['input'], ordinates, curve['bl_interpolation'], 3, base_path+'.scale'
        )
        for fcurve in fcurves:
            fcurve.group = group



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

    name = (
        animation.get('name', 'animations[%d]' % anim_id) +
        '@' + blender_object.name +
        ' (Morph)'
    )
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
        ordinates = curve['output'][i:len(curve['output']):num_targets]
        add_fcurve(op, action, curve['input'], ordinates, curve['bl_interpolation'], data_path)



def add_material_action(op, anim_id, material_id, curves):
    # Again, a separate action.
    animation = op.gltf['animations'][anim_id]
    material = op.get('material', material_id)
    node_tree = material.node_tree

    name = (
        animation.get('name', 'animations[%d]' % anim_id) +
        '@' + material.name +
        ' (Material)'
    )
    action = bpy.data.actions.new(name)
    action.id_root = 'NODETREE'
    action.use_fake_user = True

    # Play the first animation by default
    if anim_id == 0:
        node_tree.animation_data_create().action = action


    # The name of the group node in a material is currently always 'Group'
    group_node_name = 'Group'


    for prop, curve in curves.items():
        if not curve['input']:
            continue

        prop_to_input = {
            'emissiveFactor': 'EmissiveFactor',
            'alphaCutoff': 'AlphaCutoff',
            'normalTexture/scale': 'NormalScale',
            'occlusionTexture/strength': 'OcclusionStrength',
            'baseColorFactor': 'BaseColorFactor',
            'metallicFactor': 'MetallicFactor',
            'roughnessFactor': 'RoughnessFactor',
            'diffuseFactor': 'DiffuseFactor',
            'specularFactor': 'SpecularFactor',
            'glossinessFactor': 'GlossinessFactor',
        }
        if prop in prop_to_input:
            input_name = prop_to_input[prop]
            input_id = node_tree.nodes[group_node_name].inputs.find(input_name)
            if input_id == -1:
                continue

            data_path = 'nodes[%s].inputs[%d].default_value' % (quote(group_node_name), input_id)

            # TODO: we need to add alpha values to 3-component colors

            # Figure out the number of components
            try:
                num_components = len(curve['output'][0])
            except Exception:
                num_components = 1
            
            if num_components == 1:
                add_fcurve(op, action, curve['input'], curve['output'], curve['bl_interpolation'], data_path)
            else:
                add_fcurves(op, action, curve['input'], curve['output'], curve['bl_interpolation'], num_components, data_path)
            
            continue

        # Other properties would go here



def add_fcurve(op, action, input, output, interpolation, data_path, index=None):
    if index == None:
        fcurve = action.fcurves.new(data_path=data_path)
    else:
        fcurve = action.fcurves.new(data_path=data_path, index=index)
    keyframe_points = fcurve.keyframe_points
    keyframe_points.add(len(input))
    framerate = op.framerate
    for k, (t, y) in enumerate(zip(input, output)):
        keyframe_points[k].interpolation = interpolation
        keyframe_points[k].co = (t * framerate, y)
    fcurve.update()
    return fcurve

def add_fcurves(op, action, input, output, interpolation, num_components, data_path):
    assert(num_components > 1)
    fcurves = [
        action.fcurves.new(data_path=data_path, index=i) for i in range(0, num_components)
    ]
    for fcurve in fcurves:
        fcurve.keyframe_points.add(len(input))
    framerate = op.framerate
    for k, (t, ys) in enumerate(zip(input, output)):
        for i in range(0, num_components):
            fcurves[i].keyframe_points[k].interpolation = interpolation
            fcurves[i].keyframe_points[k].co = (t * framerate, ys[i])
    for fcurve in fcurves:
        fcurve.update()
    return fcurves

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
