import json
import os
import bpy

# This file creates the node groups that we use during material creation. Node
# groups are serialized in groups.json. The data comes from
# KhronosGroup/glTF-Blender-Exporter/pbr_node/glTF2.blend, plus some
# modifications.
this_dir = os.path.dirname(os.path.abspath(__file__))
node_groups_path = os.path.join(this_dir, 'groups.json')
with open(node_groups_path, 'r') as f:
    f.readline()  # throw away comment line
    GROUP_DATA = json.load(f)


def create_group(op, name):
    data = GROUP_DATA[name]

    # Before we create a new one, if there is an existing group with the right
    # name and whose inputs/outputs have the right names, (perhaps from a
    # previous import), use that instead.
    if name in bpy.data.node_groups:
        g = bpy.data.node_groups[name]
        in_names = [input.name for input in g.inputs]
        out_names = [output.name for output in g.outputs]
        matches = (
            in_names == [y['name'] for y in data['inputs']] and
            out_names == [y['name'] for y in data['outputs']]
        )
        if matches:
            return g

    g = bpy.data.node_groups.new(data['name'], 'ShaderNodeTree')
    inputs = g.inputs
    outputs = g.outputs
    nodes = g.nodes
    links = g.links

    # New groups aren't empty; empty it
    while nodes:
        nodes.remove(nodes[0])

    def deserialize_sockets(sockets, ys):
        for y in ys:
            s = sockets.new(y['idname'], y['name'])
            if 'default_value' in y:
                s.default_value = y['default_value']
            if 'min_value' in y:
                s.min_value = y['min_value']
            if 'max_value' in y:
                s.max_value = y['max_value']

    deserialize_sockets(inputs, data['inputs'])
    deserialize_sockets(outputs, data['outputs'])

    for y in data['nodes']:
        node = nodes.new(y['idname'])
        node.name = y['name']
        if 'node_tree' in y:
            node.node_tree = op.get('node_group', y['node_tree'])
        for attr in [
            'label', 'operation', 'blend_type', 'use_clamp',
            'translation', 'rotation', 'scale'
        ]:
            if attr in y:
                setattr(node, attr, y[attr])

        for i, v in enumerate(y['inputs']):
            if v != None:
                node.inputs[i].default_value = v
        for i, v in enumerate(y['outputs']):
            if v != None:
                node.outputs[i].default_value = v

    for i, y in enumerate(data['nodes']):
        if 'parent' in y:
            nodes[i].parent = nodes[y['parent']]

    for i, y in enumerate(data['nodes']):
        nodes[i].location = y['location']
        nodes[i].width = y['width']
        nodes[i].height = y['height']

    for i in range(0, len(data['links']), 4):
        a, b, c, d = data['links'][i:i+4]
        links.new(nodes[a].outputs[b], nodes[c].inputs[d])

    return g


# The rest of this file isn't used in the importer but you can use it to edit
# the serialized groups. First run load() to load all the groups, edit, and then
# serialize them back to node_groups.json with serialize().

def load():
    # Implements *just* enough of ImportGLTF to get create_group to work :)
    class ProxyOp:
        def __init__(self):
            self.node_groups = {}

        def get(self, type, name):
            assert(type == 'node_group')
            if name not in self.node_groups:
                self.node_groups[name] = create_group(self, name)
            return self.node_groups[name]

    op = ProxyOp()
    for name in GROUP_DATA.keys():
        create_group(op, name)


def serialize_group(group):
    def val(x):
        if x == None:
            return x
        if type(x) in [int, float, bool, list, str]:
            return x
        if hasattr(x, '__len__'):
            return list(x)
        assert(False)

    def serialize_sockets(sockets):
        result = []
        for s in sockets:
            x = {
                'name': s.name,
                'idname': s.bl_socket_idname,
            }
            if hasattr(s, 'default_value'):
                x['default_value'] = val(s.default_value)
            if hasattr(s, 'min_value'):
                x['min_value'] = val(s.min_value)
            if hasattr(s, 'max_value'):
                x['max_value'] = val(s.max_value)
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

        if node.parent:
            x['parent'] = node_to_idx[node.parent]
        if hasattr(node, 'label') and node.label != '':
            x['label'] = node.label
        if hasattr(node, 'node_tree'):
            x['node_tree'] = node.node_tree.name

        for attr in [
            'operation', 'blend_type', 'use_clamp',
            'translation', 'rotation', 'scale',
        ]:
            if hasattr(node, attr):
                x[attr] = val(getattr(node, attr))

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


def serialize():
    groups = {}
    for group in bpy.data.node_groups:
        groups[group.name] = serialize_group(group)

    with open(node_groups_path, 'w') as f:
        f.write('// !!AUTO-GENERATED!! See node_groups.py\n')
        f.write('{\n')
        keys = list(groups.keys())
        keys.sort()
        for k in keys:
            json.dump(k, f)
            f.write(':')
            json.dump(groups[k], f, separators=(',', ':'))
            if k != keys[-1]:
                f.write(',')
            f.write('\n')
        f.write('}\n')
