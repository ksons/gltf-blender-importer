import bpy

def create_mesh(importer, idx):
    mesh = importer.root['meshes'][idx]
    name = mesh.get('name', 'meshes[%d]' % idx)
    me = bpy.data.meshes.new(name)

    #TODO handle multiple primitives
    primitive = mesh['primitives'][0]
    if 'material' in primitive:
        material = importer.get_material(primitive['material'])
    else:
        material = importer.get_default_material()
    me.materials.append(material)
    #TODO handle no indices
    indices = importer.get_accessor(primitive['indices'])
    #TODO handle primitive mode != 4
    faces = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]

    attributes = primitive['attributes']
    positions = importer.get_accessor(attributes['POSITION'])

    me.from_pydata(positions, [], faces)
    me.validate(verbose = True)

    for polygon in me.polygons:
        polygon.use_smooth = True

    if 'NORMAL' in attributes:
        normals = importer.get_accessor(attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = normals[i]

    if 'TEXCOORD_0' in attributes:
        uvs = importer.get_accessor(attributes['TEXCOORD_0'])
        me.uv_textures.new("TEXCOORD_0")
        for i, uv_loop in enumerate(me.uv_layers[0].data):
            uv = uvs[indices[i]]
            me.uv_layers[0].data[i].uv = (uv[0], -uv[1])

    me.update()
    return me
