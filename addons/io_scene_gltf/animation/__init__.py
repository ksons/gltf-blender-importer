import json, re

# Utility method; quotes a string using double quotes
def quote(s):
    return json.dumps(s)

from .node_trs import add_node_trs_animation
from .morph_weight import add_morph_weight_animation
from .material import add_material_animation

# We need to gather information about the animations before we begin importing.
# The main reason is we need to know during material creation whether a
# particular texture will have a texture transform animation.
#
# We also go ahead and reorganize the data in the glTF animation into a more
# structured form that's easier to process later on. An _animation info_ looks
# like this
#
# {
#   'node_trs': {
#     Node Id: { ('translation'|'rotation'|'scale': sampler }
#   }
#   'morph_weight': { Node Id: sampler }
#   'material': {
#     Material Id: {
#       'properties': { property name: sampler },
#       'texture_transform': {
#         texture_type: { ('offset'|'rotation'|'scale'): sampler }
#       }
#     }
#   }
# }
#
# op.animations_info is a map from animation IDs to animation infos.

def gather_animation_info(op):
    animations = op.gltf.get('animations', [])
    op.animation_info = [
        gather_animation(op, anim_id)
        for anim_id in range(0, len(animations))
    ]

def first_match(patterns, s):
    for pattern in patterns:
        match = re.match(pattern, s)
        if match: return match
    return None

def gather_animation(op, anim_id):
    anim = op.gltf['animations'][anim_id]
    samplers = anim['samplers']

    info = {
        'node_trs': {},
        'morph_weight': {},
        'material': {},
    }

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
            info['node_trs'].setdefault(node_id, {})[path] = sampler
        elif path == 'weights':
            info['morph_weight'][node_id] = sampler
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
            info['node_trs'].setdefault(int(node_id), {})[path] = sampler
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
            (info['material']
                .setdefault(int(material_id), {})
                .setdefault('properties', {})
            )[prop] = sampler
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
            (info['material']
                .setdefault(int(material_id), {})
                .setdefault('texture_transform', {})
                .setdefault(texture_type, {})
            )[path] = sampler

            # Make a note that this material/texture has a transform animation.
            op.material_texture_has_animated_transform[(int(material_id), texture_type)] = True

            continue

        print('skipping animation curve, target not supported: %s' % target)

    return info


# After we've created the scene, we can add in the actual animations.
def add_animations(op):
    for anim_id, info in enumerate(op.animation_info):
        for node_id, data in info['node_trs'].items():
            add_node_trs_animation(op, anim_id, node_id, data)

        for node_id, sampler in info['morph_weight'].items():
            add_morph_weight_animation(op, anim_id, node_id, sampler)

        for material_id, data in info['material'].items():
            add_material_animation(op, anim_id, material_id, data)
