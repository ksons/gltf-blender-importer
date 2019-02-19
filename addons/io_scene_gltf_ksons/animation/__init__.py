import json
import re

def quote(s):
    """Quote a string with double-quotes."""
    return json.dumps(s)

from .precompute import animation_precomputation
from .node_trs import add_node_trs_animation
from .morph_weight import add_morph_weight_animation
from .material import add_material_animation

# After we've created the forest, we can add in the actual animations.
def add_animations(op):
    for anim_info in op.animation_info:
        for node_id in anim_info.node_trs:
            add_node_trs_animation(op, anim_info, node_id)

        for node_id in anim_info.morph_weight:
            add_morph_weight_animation(op, anim_info, node_id)

        for material_id in anim_info.material:
            add_material_animation(op, anim_info, material_id)
