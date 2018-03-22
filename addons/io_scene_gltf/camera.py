import bpy


def create_camera(op, idx):
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
    else:
        camera.type = "PERSP"
        p = data["perspective"]
        camera.clip_start = p["znear"]
        camera.clip_end = p["zfar"]
        camera.lens_unit = "FOV"
        camera.angle_x = p["yfov"] * p["aspectRatio"]
    return camera
