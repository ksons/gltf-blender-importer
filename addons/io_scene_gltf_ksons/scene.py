import bpy

if bpy.app.version >= (2, 80, 0):
    def link_vnode_into_scene(vnode, scene):
        if vnode.blender_object:
            if vnode.blender_object.name not in scene.collection.objects:
                scene.collection.objects.link(vnode.blender_object)
else:
    def link_vnode_into_scene(vnode, scene):
        if vnode.blender_object:
            try:
                scene.objects.link(vnode.blender_object)
            except Exception:
                # Ignore exception if its already linked
                pass


def link_tree_into_scene(vnode, scene):
    link_vnode_into_scene(vnode, scene)
    for child in vnode.children:
        link_tree_into_scene(child, scene)


def link_ancestors_into_scene(vnode, scene):
    while vnode:
        link_vnode_into_scene(vnode, scene)
        vnode = vnode.parent


def create_blender_scenes(op):
    if op.import_into_current_scene:
        # Link everything into the current scene
        link_tree_into_scene(op.root_vnode, bpy.context.scene)
        bpy.context.scene.render.engine = 'CYCLES'
        return

    # Creates scenes to match the glTF scenes

    default_scene_id = op.gltf.get('scene')

    scenes = op.gltf.get('scenes', [])
    for i, scene in enumerate(scenes):
        name = scene.get('name', 'scenes[%d]' % i)
        blender_scene = bpy.data.scenes.new(name)
        blender_scene.render.engine = 'CYCLES'

        roots = scene.get('nodes', [])
        for node_id in roots:
            vnode = op.node_id_to_vnode[node_id]

            link_ancestors_into_scene(vnode, blender_scene)
            link_tree_into_scene(vnode, blender_scene)

            # Select this scene if it is the default
            if i == default_scene_id:
                if bpy.app.version >= (2, 80, 0):
                    bpy.context.window.scene = blender_scene
                else:
                    bpy.context.screen.scene = blender_scene
