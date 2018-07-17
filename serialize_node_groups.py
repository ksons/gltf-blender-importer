# This file serializes all the node groups in a .blend to a JSON format.
# (Actually, the serialization is only partial, but it's enough for our
# purposes. Using rna2xml instead seems logical but I couldn't get it working.)
#
# This is used to generate node_groups.json which contains the node group data
# for KhronosGroup/glTF-Blender-Exporter/pbr_node/glTF2.blend, plus some
# modifications.
#
# Instruction: You run this script from Blender. Open the glTF2.blend file, then
# open this file in the text editor and hit 'Run Script'. The output is placed
# in out.json in the current dir.


import json
import bpy


def val(x):
    if type(x) == float: return x
    return list(x)


def serialize_group(group):
    def serialize_sockets(sockets):
        result = []
        for s in sockets:
            x = {
                'name': s.name,
                'idname': s.bl_socket_idname,
            }
            if hasattr(s, 'default_value'): x['default_value'] = val(s.default_value)
            if hasattr(s, 'min_value'): x['min_value'] = val(s.min_value)
            if hasattr(s, 'max_value'): x['max_value'] = val(s.max_value)
            result.append(x)
        return result

    inputs = serialize_sockets(group.inputs)
    outputs = serialize_sockets(group.outputs)


    node_to_idx = {}
    for i, node in enumerate(group.nodes):
        node_to_idx[node] = i

    nodes = []
    for node in group.nodes:
        x = {
            'name': node.name,
            'idname': node.bl_idname,
            'location': val(node.location),
            'width': node.width,
            'height': node.height,
            'inputs': [],
            'outputs': [],
        }
        if node.parent: x['parent'] = node_to_idx[node.parent]
        if hasattr(node, 'operation'): x['operation'] = node.operation
        if hasattr(node, 'blend_type'): x['blend_type'] = node.blend_type
        if hasattr(node, 'use_clamp'): x['use_clamp'] = node.use_clamp
        if hasattr(node, 'label') and node.label != '': x['label'] = node.label
        if hasattr(node, 'node_tree'): x['node_tree'] = node.node_tree.name

        for input in node.inputs:
            if input.links or not hasattr(input, 'default_value'):
                x['inputs'].append(None)
            else:
                x['inputs'].append(val(input.default_value))
        for output in node.outputs:
            if output.links or not hasattr(output, 'defaultvalue'):
                x['outputs'].append(None)
            else:
                x['outputs'].append(val(output.default_value))

        nodes.append(x)


    links = []
    for link in group.links:
        from_node_id = node_to_idx[link.from_node]
        from_socket_id = list(link.from_node.outputs).index(link.from_socket)
        to_node_id = node_to_idx[link.to_node]
        to_socket_id = list(link.to_node.inputs).index(link.to_socket)
        links += [from_node_id, from_socket_id, to_node_id, to_socket_id]


    return {
        'name': group.name,
        'inputs': inputs,
        'outputs': outputs,
        'nodes': nodes,
        'links': links,
    }


def serialize_all_groups():
    groups = {}
    for group in bpy.data.node_groups:
        groups[group.name] = serialize_group(group)
    return groups



with open('out.json', 'w') as f:
    f.write('// !!AUTO-GENERATED!! See serialize_node_groups.py\n')
    json.dump(serialize_all_groups(), f, separators=(',',':'))
