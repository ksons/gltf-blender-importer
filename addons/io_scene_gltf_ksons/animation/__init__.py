import json
import bpy

def quote(s):
    """Quote a string with double-quotes."""
    return json.dumps(s)

from .precompute import animation_precomputation
from .node_trs import add_node_trs_animation
from .morph_weight import add_morph_weight_animation
from .material import add_material_animation

def add_animations(op):
    for anim_info in op.animation_info:
        for node_id in anim_info.node_trs:
            add_node_trs_animation(op, anim_info, node_id)

        for node_id in anim_info.morph_weight:
            add_morph_weight_animation(op, anim_info, node_id)

        for material_id in anim_info.material:
            add_material_animation(op, anim_info, material_id)

    create_nla_tracks(op)


def create_nla_tracks(op):
    """
    Put all the actions in NLA tracks, each animation one after the other in one
    big timeline.
    """
    def get_track(bl_thing, track_name):
        if not bl_thing.animation_data:
            bl_thing.animation_data_create()

        if track_name not in bl_thing.animation_data.nla_tracks:
            track = bl_thing.animation_data.nla_tracks.new()
            track.name = track_name

        return bl_thing.animation_data.nla_tracks[track_name]

    t = 0.0  # Start time in the big timeline
    padding = 5.0  # Padding time between animations

    for anim_info in op.animation_info:
        anim_id = anim_info.anim_id
        anim_name = op.gltf['animations'][anim_id].get('name', 'animations[%d]' % anim_id)

        for object_name, action in anim_info.trs_actions.items():
            bl_object = bpy.data.objects[object_name]
            track = get_track(bl_object, 'Position')
            track.strips.new(anim_name, t, action)

        for object_name, action in anim_info.morph_actions.items():
            shape_keys = bpy.data.objects[object_name].data.shape_keys
            track = get_track(shape_keys, 'Morph')
            track.strips.new(anim_name, t, action)

        for material_id, action in anim_info.material_actions.items():
            node_tree = op.get('material', material_id).node_tree
            track = get_track(node_tree, 'Material')
            track.strips.new(anim_name, t, action)

        t += anim_info.duration + padding
