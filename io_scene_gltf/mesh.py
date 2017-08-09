import bmesh
import bpy

def primitive_to_mesh(op, primitive, material_index):
    mode = primitive.get('mode', 4)
    attributes = primitive['attributes']
    if 'indices' in primitive:
        indices = op.get_accessor(primitive['indices'])
    else:
        indices = None

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

    me = bpy.data.meshes.new('>>>TEMP<<<')
    me.from_pydata(verts, edges, faces)
    me.validate()

    for polygon in me.polygons:
        polygon.material_index = material_index

    if 'NORMAL' in attributes:
        normals = op.get_accessor(attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = normals[i]

    if 'TEXCOORD_0' in attributes:
        uvs = op.get_accessor(attributes['TEXCOORD_0'])
        me.uv_textures.new("TEXCOORD_0")
        for i, uv_loop in enumerate(me.uv_layers[0].data):
            uv = uvs[indices[i]] #TODO what about when indices == None?
            uv_loop.uv = (uv[0], -uv[1])

    me.update()

    return me


def create_mesh(op, idx):
    mesh = op.root['meshes'][idx]
    name = mesh.get('name', 'meshes[%d]' % idx)
    me = bpy.data.meshes.new(name)

    bme = bmesh.new()
    for i, primitive in enumerate(mesh['primitives']):
        tmp_mesh = primitive_to_mesh(op, primitive, i)
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
