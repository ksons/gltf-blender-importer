import os
import bpy


def link_vnode_into_collection(vnode, collection):
    if vnode.blender_object:
        if vnode.blender_object.name not in collection.objects:
            collection.objects.link(vnode.blender_object)


def link_tree_into_collection(vnode, collection):
    link_vnode_into_collection(vnode, collection)
    for child in vnode.children:
        link_tree_into_collection(child, collection)


def import_scenes_as_collections(op):
    if getattr(bpy.data, 'collections', None) is None:
        print(
            "Can't import scenes as collections; "
            'no collections in this Blender version!'
        )
        return

    scenes = op.gltf.get('scenes', [])
    if not scenes:
        return

    base_collection = bpy.data.collections.new(os.path.basename(op.filepath))

    default_scene_idx = op.gltf.get('scene')
    for scene_idx, scene in enumerate(op.gltf.get('scenes', [])):
        name = scene.get('name', 'scenes[%d]' % scene_idx)
        if scene_idx == default_scene_idx:
            name += ' (Default)'

        collection = bpy.data.collections.new(name)
        base_collection.children.link(collection)

        for node_idx in scene['nodes']:
            vnode = op.node_id_to_vnode[node_idx]

            # A root node might not be a root vnode (eg. because we inserted an
            # armature above it). Find the real root.
            while vnode.parent is not None and vnode.parent.parent is not None:
                vnode = vnode.parent

            link_tree_into_collection(vnode, collection)
