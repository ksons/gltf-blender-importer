import re
import bpy

class AnimationInfo:
    def __init__(self, anim_id):
        self.anim_id = anim_id

        # These are for organizing the samplers by the object they affect.
        # Filled out during precomputation.

        # node_trs[node_idx]['translation'/'rotation'/'scale'] is the sampler
        # for that node's TRS property
        self.node_trs = {}
        # morph_weight[node_idx] is the sampler for that node's morph weights
        self.morph_weight = {}
        # material[material_idx][property name] is the sampler for that
        # materials' property
        # material[material_idx]['texture_transform'][texture_type]['offset'/'rotation'/'scale']
        # is the sampler for texture transform values
        self.material = {}
        # Duration of longest input sampler
        self.duration = 0.0

        # trs_actions[object_blender_name] records the TRS action on that object.
        self.trs_actions = {}
        # trs_actions[object_blender_name] records the morph weight (shape key)
        # action on that object.
        self.morph_actions = {}
        # material_actions[material_id] records the action on that material.
        self.material_actions = {}


def animation_precomputation(op):
    """Precompute AnimationInfo for each animation."""
    animations = op.gltf.get('animations', [])
    op.animation_info = [
        gather_animation(op, anim_id)
        for anim_id in range(0, len(animations))
    ]


def first_match(patterns, s):
    for pattern in patterns:
        match = re.match(pattern, s)
        if match:
            return match
    return None


def gather_animation(op, anim_id):
    anim = op.gltf['animations'][anim_id]
    samplers = anim['samplers']

    info = AnimationInfo(anim_id)

    framerate = op.options['framerate']
    if framerate <= 0:
        framerate = bpy.context.scene.render.fps
    def calc_duration(sampler):
        acc = op.gltf['accessors'][sampler['input']]
        max_time = framerate * acc['max'][0]
        info.duration = max(info.duration, max_time)

    # Normal glTF channels
    channels = anim['channels']
    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']
        if 'node' not in target:
            continue
        node_id = target['node']
        path = target['path']

        if path in ['translation', 'rotation', 'scale']:
            info.node_trs.setdefault(node_id, {})[path] = sampler
            calc_duration(sampler)
        elif path == 'weights':
            info.morph_weight[node_id] = sampler
            calc_duration(sampler)
        else:
            print('skipping animation curve, unknown path: %s' % path)
            continue

    # EXT_property_animation channels
    channels = (
        anim.get('extensions', {})
        .get('EXT_property_animation', {})
        .get('channels', [])
    )
    for channel in channels:
        sampler = samplers[channel['sampler']]
        target = channel['target']

        # Node TRS properties
        patterns = [
            r'^/nodes/(\d+)/(translation|rotation|scale)$',
        ]
        match = first_match(patterns, target)
        if match:
            node_id, path = match.groups()
            info.node_trs.setdefault(int(node_id), {})[path] = sampler
            calc_duration(sampler)
            continue

        # Simple material properties
        patterns = [
            r'^/materials/(\d+)/(emissiveFactor|alphaCutoff)$',
            r'^/materials/(\d+)/(normalTexture/scale|occlusionTexture/strength)$',
            r'^/materials/(\d+)/pbrMetallicRoughness/(baseColorFactor|metallicFactor|roughnessFactor)$',
            r'^/materials/(\d+)/extensions/KHR_materials_pbrSpecularGlossiness/(diffuseFactor|specularFactor|glossinessFactor)$',
        ]
        match = first_match(patterns, target)
        if match:
            material_id, prop = match.groups()
            (info.material
                .setdefault(int(material_id), {})
                .setdefault('properties', {})
             )[prop] = sampler
            calc_duration(sampler)

            # Record that this property is live (so don't skip it during material creation)
            op.material_infos[int(material_id)].liveness.add(prop)

            continue

        # Texture transform properties
        patterns = [
            r'^/materials/(\d+)/(normalTexture|occlusionTexture|emissiveTexture)/extensions/KHR_texture_transform/(offset|rotation|scale)$',
            r'^/materials/(\d+)/pbrMetallicRoughness/(baseColorTexture|metallicRoughnessTexture)/extensions/KHR_texture_transform/(offset|rotation|scale)$',
            r'^/materials/(\d+)/extensions/KHR_materials_pbrSpecularGlossiness/(diffuseTexture|specularGlossinessTexture)/extensions/KHR_texture_transform/(offset|rotation|scale)$',
        ]
        match = first_match(patterns, target)
        if match:
            material_id, texture_type, path = match.groups()
            (info.material
                .setdefault(int(material_id), {})
                .setdefault('texture_transform', {})
                .setdefault(texture_type, {})
             )[path] = sampler

            # Record that this property is live (don't skip it during material creation)
            op.material_infos[int(material_id)].liveness.add(texture_type + '-transform')

            continue

        print('skipping animation curve, target not supported: %s' % target)

    return info
