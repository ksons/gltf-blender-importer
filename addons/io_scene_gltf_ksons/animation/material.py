import bpy
from . import quote
from .curve import Curve


def add_material_animation(op, anim_id, material_id, data):
    animation = op.gltf['animations'][anim_id]
    material = op.get('material', material_id)
    node_tree = material.node_tree

    name = '%s@%s (Material)' % (
        animation.get('name', 'animations[%d]' % anim_id),
        material.name,
    )
    action = bpy.data.actions.new(name)
    action.use_fake_user = True

    # Play the first animation by default
    if anim_id == 0:
        node_tree.animation_data_create().action = action

    fcurves = []

    for prop, sampler in data.get('properties', {}).items():
        curve = Curve.for_sampler(op, sampler)
        data_path = op.material_infos[material_id].paths[prop]
        fcurves += curve.make_fcurves(op, action, data_path)

    if fcurves:
        group = action.groups.new('Material Property')
        for fcurve in fcurves:
            fcurve.group = group

    for texture_type, samplers in data.get('texture_transform', {}).items():
        base_path = op.material_infos[material_id].paths[texture_type + '-transform']

        fcurves = []

        if 'offset' in samplers:
            curve = Curve.for_sampler(op, samplers['offset'])
            data_path = base_path + '.translation'
            fcurves += curve.make_fcurves(op, action, data_path)

        if 'rotation' in samplers:
            curve = Curve.for_sampler(op, samplers['rotation'])
            data_path = [(base_path + '.rotation', 2)]  # animate rotation around Z-axis
            fcurves += curve.make_fcurves(op, action, data_path, transform=lambda theta:-theta)

        if 'scale' in samplers:
            curve = Curve.for_sampler(op, samplers['scale'])
            data_path = base_path + '.scale'
            fcurves += curve.make_fcurves(op, action, data_path)

        group_name = {
            'normalTexture': 'Normal',
            'occlusionTexture': 'Occlusion',
            'emissiveTexture': 'Emissive',
            'baseColorTexture': 'Base Color',
            'metallicRoughnessTexture': 'Metallic-Roughness',
            'diffuseTexture': 'Diffuse',
            'specularGlossinessTexture': 'Specular-Glossiness',
        }[texture_type] + ' Texture Transform'
        group = action.groups.new(group_name)
        for fcurve in fcurves:
            fcurve.group = group
