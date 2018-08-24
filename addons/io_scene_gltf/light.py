import math
import bpy


def create_light(op, idx):
    light = op.gltf['extensions']['KHR_lights_punctual']['lights'][idx]
    name = light.get('name', 'lights[%d]' % idx)

    type = light['type']
    color = light.get('color', [1, 1, 1])
    intensity = light.get('intensity', 1)

    bl_type = {
        'directional': 'SUN',
        'point': 'POINT',
        'spot': 'SPOT',
    }.get(type)
    if not bl_type:
        print('unknown light type:', type)
        bl_type = 'POINT'

    lamp = bpy.data.lamps.new(name, type=bl_type)
    lamp.use_nodes = True

    emission = lamp.node_tree.nodes['Emission']
    emission.inputs['Color'].default_value = tuple(color) + (1,)

    if type == 'directional':
        watt = lux2W(intensity, ideal_555nm_source)
        emission.inputs['Strength'].default_value = watt
    elif type == 'point':
        watt = cd2W(intensity, ideal_555nm_source, surface=4*math.pi)
        emission.inputs['Strength'].default_value = watt
    elif type == 'spot':
        spot = light.get('spot', {})
        inner = spot.get('innerConeAngle', 0)
        outer = spot.get('outerConeAngle', math.pi/4)
        lamp.spot_size = outer
        lamp.spot_blend = inner / outer

        # For the surface calc see:
        # https://en.wikipedia.org/wiki/Solid_angle#Cone,_spherical_cap,_hemisphere
        emission.inputs['Strength'].default_value = cd2W(
            intensity,
            ideal_555nm_source,
            surface=2 * math.pi * (1 - math.cos(outer / 2)),
        )
    else:
        assert(False)

    return lamp


# Wat conversions

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
