import bpy


def create_camera(op, idx):
    """Create a Blender camera for the glTF cameras[idx]."""
    data = op.gltf['cameras'][idx]
    name = data.get('name', 'cameras[%d]' % idx)
    camera = bpy.data.cameras.new(name)

    if data['type'] == 'orthographic':
        camera.type = 'ORTHO'
        p = data['orthographic']
        camera.clip_start = p['znear']
        camera.clip_end = p['zfar']
        # TODO: should we warn if xmag != ymag?
        camera.ortho_scale = max(p['xmag'], p['ymag'])

    elif data['type'] == 'perspective':
        camera.type = 'PERSP'
        p = data['perspective']
        camera.clip_start = p['znear']
        # according to the spec a missing zfar means "infinite"
        HUGE = 3.40282e+38
        camera.clip_end = p.get('zfar', HUGE)
        camera.lens_unit = 'FOV'
        camera.angle_y = p['yfov']

        # TODO: aspect ratio

    else:
        print('unknown camera type: %s' % data['type'])

    return camera
