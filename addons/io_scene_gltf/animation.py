import bpy


def create_action(op, idx):
    anim = op.gltf['animations'][idx]
    name = anim.get('name', 'animations[%d]' % idx)

    action = bpy.data.actions.new(name)
    return action
