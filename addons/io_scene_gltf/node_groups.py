import json, os
import bpy


# Load the serialized group data. Serialized data comes from
# KhronosGroup/glTF-Blender-Exporter/pbr_node/glTF2.blend, plus some
# modifications.
this_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(this_dir, 'node_groups.json'), 'r') as f:
    f.readline() # throw away comment line
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
            if 'default_value' in y: s.default_value = y['default_value']
            if 'min_value' in y: s.min_value = y['min_value']
            if 'max_value' in y: s.max_value = y['max_value']

    deserialize_sockets(inputs, data['inputs'])
    deserialize_sockets(outputs, data['outputs'])


    for y in data['nodes']:
        node = nodes.new(y['idname'])
        node.name = y['name']
        if 'label' in y: node.label = y['label']
        if 'operation' in y: node.operation = y['operation']
        if 'blend_type' in y: node.blend_type = y['blend_type']
        if 'use_clamp' in y: node.use_clamp = y['use_clamp']
        if 'node_tree' in y: node.node_tree = op.get('node_group', y['node_tree'])

        for i, v in enumerate(y['inputs']):
            if v != None: node.inputs[i].default_value = v
        for i, v in enumerate(y['outputs']):
            if v != None: node.outputs[i].default_value = v

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


# NOTE: Not part of the importer. When run as a script inside Blender, imports
# all the serialized node groups. Can be used to edit the serialized groups by
# running this in an empty file, editing, then running the serialize_node_groups
# script. You'll have to set this_dir above manually though.
if __name__ == '__main__':
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
