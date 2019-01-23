import math
import bpy


def create_light(op, idx):
    light = op.gltf['extensions']['KHR_lights_punctual']['lights'][idx]
    name = light.get('name', 'lights[%d]' % idx)

    light_type = light['type']
    color = light.get('color', [1, 1, 1])
    intensity = light.get('intensity', 1)

    bl_type = {
        'directional': 'SUN',
        'point': 'POINT',
        'spot': 'SPOT',
    }.get(light_type)
    if not bl_type:
        print('unknown light type:', type)
        bl_type = 'POINT'

    if bpy.app.version >= (2, 80, 0):
        bl_light = bpy.data.lights.new(name, type=bl_type)
    else:
        bl_light = bpy.data.lamps.new(name, type=bl_type)
    bl_light.use_nodes = True

    emission = bl_light.node_tree.nodes['Emission']
    emission.inputs['Color'].default_value = tuple(color) + (1,)

    if light_type == 'directional':
        watt = lux2W(intensity, ideal_555nm_source)
        emission.inputs['Strength'].default_value = watt
    elif light_type == 'point':
        watt = cd2W(intensity, ideal_555nm_source, surface=4*math.pi)
        emission.inputs['Strength'].default_value = watt
    elif light_type == 'spot':
        spot = light.get('spot', {})
        inner = spot.get('innerConeAngle', 0)
        outer = spot.get('outerConeAngle', math.pi/4)
        bl_light.spot_size = outer
        bl_light.spot_blend = inner / outer

        # For the surface calc see:
        # https://en.wikipedia.org/wiki/Solid_angle#Cone,_spherical_cap,_hemisphere
        emission.inputs['Strength'].default_value = cd2W(
            intensity,
            ideal_555nm_source,
            surface=2 * math.pi * (1 - math.cos(outer / 2)),
        )
    else:
        assert(False)

    return bl_light


# Watt conversions

incandescent_bulb = 0.0249
ideal_555nm_source = 1 / 683


def cd2W(intensity, efficiency, surface):
    """
    intensity in candles
    efficency is a factor
    surface in steradians
    """
    lumens = intensity * surface
    return lumens / (efficiency * 683)


def lux2W(intensity, efficiency):
    """
    intensity in lux (lm/m2)
    efficency is a factor
    """
    return intensity / (efficiency * 683)
