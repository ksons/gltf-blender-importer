from functools import reduce

import bmesh
import bpy

def primitive_to_mesh(op, primitive, all_attributes, material_index):
    """Convert a glTF primitive object to a Blender mesh.

    If you have one mesh that has some layer (texcoords, say) and
    another that doesn't, when you merge them with bmesh it seems to
    drop the layer. To prevent this, the all_attributes set contains
    the union of all the attributes from the primitives for the (glTF)
    mesh that this primitive is contained in so we can always create
    enough layers.

    """
    mode = primitive.get('mode', 4)
    attributes = primitive['attributes']
    if 'indices' in primitive:
        indices = op.get_accessor(primitive['indices'])
    else:
        indices = None

    me = bpy.data.meshes.new('{{{TEMP}}}')

    if 'POSITION' not in attributes:
        # Early out if there's no POSITION data
        return me

    verts = op.get_accessor(attributes['POSITION'])
    edges = []
    faces = []

    if mode == 0:
        # POINTS
        pass
    elif mode == 1:
        #LINES
        if not indices:
            indices = range(0, len(verts))
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices), 2)]
    elif mode == 4:
        #TRIANGLES
        if not indices:
            indices = range(0, len(verts))
        faces = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]
    else:
        raise Exception("primitive mode unimplemented: %d" % mode)

    me.from_pydata(verts, edges, faces)
    me.validate()

    for polygon in me.polygons:
        polygon.material_index = material_index

    if 'NORMAL' in attributes:
        normals = op.get_accessor(attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = normals[i]

    #TODO test this!
    if 'COLOR_0' in all_attributes:
        me.vertex_colors.new('COLOR_0')
    if 'COLOR_0' in all_attributes:
        colors = op.get_accessor(attributes['COLOR_0'])
        color_layer = me.vertex_colors[0].data
        for polygon in me.polygons:
            for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                color_layer[loop_idx].color = colors[vert_idx]

    def assign_texcoords(uvs, uv_layer):
        for polygon in me.polygons:
            for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                uv = uvs[vert_idx]
                uv_layer[loop_idx].uv = (uv[0], -uv[1])
    if 'TEXCOORD_0' in all_attributes or 'TEXCOORD_1' in all_attributes:
        me.uv_textures.new('TEXCOORD_0')
    if 'TEXCOORD_1' in all_attributes:
        me.uv_textures.new('TEXCOORD_1')
    if 'TEXCOORD_0' in attributes:
        assign_texcoords(op.get_accessor(attributes['TEXCOORD_0']), me.uv_layers[0].data)
    if 'TEXCOORD_1' in attributes:
        assign_texcoords(op.get_accessor(attributes['TEXCOORD_1']), me.uv_layers[1].data)

    if 'JOINTS_0' in attributes and 'WEIGHTS_0' in attributes:
        # Don't seem to need to deal with all_attributes here.
        # The only way I could find to set vertex groups was by
        # round-tripping through a bmesh.
        #TODO find a better way?
        joints = op.get_accessor(attributes['JOINTS_0'])
        weights = op.get_accessor(attributes['WEIGHTS_0'])
        bme = bmesh.new()
        bme.from_mesh(me)
        layer = bme.verts.layers.deform.new('JOINTS_0')
        for vert, joint_vec, weight_vec in zip(bme.verts, joints, weights):
            for joint, weight in zip(joint_vec, weight_vec):
                vert[layer][joint] = weight
        bme.to_mesh(me)
        bme.free()

    me.update()

    return me


def create_mesh(op, idx):
    mesh = op.gltf['meshes'][idx]
    name = mesh.get('name', 'meshes[%d]' % idx)
    primitives = mesh['primitives']
    me = bpy.data.meshes.new(name)

    # Find the union of the attributes used by each primitive.
    attributes = (set(primitive['attributes'].keys()) for primitive in primitives)
    all_attributes = reduce(lambda x,y: x.union(y), attributes)

    bme = bmesh.new()
    for i, primitive in enumerate(mesh['primitives']):
        tmp_mesh = primitive_to_mesh(op, primitive, all_attributes, i)
        bme.from_mesh(tmp_mesh)
        bpy.data.meshes.remove(tmp_mesh)
    bme.to_mesh(me)
    bme.free()

    for primitive in mesh['primitives']:
        if 'material' in primitive:
            material = op.get_material(primitive['material'])
        else:
            material = op.get_default_material()
        me.materials.append(material)

    for polygon in me.polygons:
        polygon.use_smooth = True

    me.update()

    return me
