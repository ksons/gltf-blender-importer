import bpy
import math


def create_camera(op, idx, scene):
    """
    create a new blender camera from the gltf data
    """
    data = op.gltf['cameras'][idx]
    name = data.get('name', 'cameras[%d]' % idx)
    camera = bpy.data.cameras.new(name)
    if data["type"] == "orthographic":
        camera.type = "ORTHO"
        p = data["orthographic"]
        camera.clip_start = p["znear"]
        camera.clip_end = p["zfar"]
        camera.ortho_scale = max(p["xmag"], p["ymag"])
    elif data["type"] == "perspective":
        camera.type = "PERSP"
        p = data["perspective"]
        camera.clip_start = p["znear"]
        # according to the spec a missing zfar means "infinite"
        camera.clip_end = p.get("zfar", math.inf)
        camera.lens_unit = "FOV"
        camera.angle_y = p["yfov"]

        # The aspectRatio is optional and if given, it is used to change the
        # width resolution
        aspectRatio = p.get("aspectRatio")
        if aspectRatio:
            scene.render.resolution_x = scene.render.resolution_y * aspectRatio
    else:
        # this branch should never been taken since the only camera types are
        # "orthographic" and "perspective"; but if the input document use an
        # unexpected type we prefer to return an unitialized camera instead of
        # stop the import with an error
        pass
    return camera
