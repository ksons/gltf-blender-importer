import bpy


def create_camera(op, idx):
    camera = op.gltf['cameras'][idx]
    name = camera.get('name', 'cameras[%d]' % idx)
    data = bpy.data.cameras.new(name)
    return data
