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
    me = bpy.data.meshes.new('{{{TEMP}}}')
    attributes = primitive['attributes']

    if 'POSITION' not in attributes:
        # Early out if there's no POSITION data
        return me

    verts = op.get_accessor(attributes['POSITION'])
    edges = []
    faces = []

    # Generate the topology

    mode = primitive.get('mode', 4)

    if 'indices' in primitive:
        indices = op.get_accessor(primitive['indices'])
    else:
        indices = range(0, len(verts))

    # TODO: only mode TRIANGLES is tested!!
    if mode == 0:
        # POINTS
        pass
    elif mode == 1:
        # LINES
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices), 2)]
    elif mode == 2 or mode == 3:
        # LINE LOOP/STRIP
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices) - 1)]
        if mode == 2:
            edges.append((indices[-1], indices[0]))
    elif mode == 4:
        # TRIANGLES
        #   2     3
        #  / \   / \
        # 0---1 4---5
        faces = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]
    elif mode == 5:
        # TRIANGLE STRIP
        #   1---3---5
        #  / \ / \ /
        # 0---2---4
        def alternate(i, xs):
            ccw = i % 2 != 0
            return xs if ccw else (xs[0], xs[2], xs[1])
        faces = [
            alternate(i, tuple(indices[i:i+3]))
            for i in range(0, len(indices) - 2)
        ]
    elif mode == 6:
        # TRIANGLE FAN
        #   3---2
        #  / \ / \
        # 4---0---1
        faces = [
            (indices[0], indices[i], indices[i+1])
            for i in range(1, len(indices) - 1)
        ]
    else:
        raise Exception("primitive mode unimplemented: %d" % mode)

    me.from_pydata(verts, edges, faces)
    me.validate()

    # Assign material
    for polygon in me.polygons:
        polygon.material_index = material_index

    # Assign normals
    if 'NORMAL' in attributes:
        normals = op.get_accessor(attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = normals[i]

    # Assign colors
    if 'COLOR_0' in all_attributes:
        me.vertex_colors.new('COLOR_0')
    if 'COLOR_0' in attributes:
        colors = op.get_accessor(attributes['COLOR_0'])
        if colors and len(colors[0]) == 4:
            print(
                'WARNING! This glTF uses RGBA vertex colors. Blender only supports '
                'RGB vertex colors. The alpha component will be discarded.'
            )

        color_layer = me.vertex_colors[0].data
        for polygon in me.polygons:
            for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                color_layer[loop_idx].color = colors[vert_idx][0:3]

    # Assign texcoords
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

    # TODO: handle joints and weights

    me.update()

    return me


def create_mesh(op, idx):
    mesh = op.gltf['meshes'][idx]
    name = mesh.get('name', 'meshes[%d]' % idx)
    primitives = mesh['primitives']
    me = bpy.data.meshes.new(name)

    # Find the union of the attributes used by each primitive.
    attributes = (set(primitive['attributes'].keys()) for primitive in primitives)
    all_attributes = reduce(lambda x, y: x.union(y), attributes)

    bme = bmesh.new()
    for i, primitive in enumerate(mesh['primitives']):
        tmp_mesh = primitive_to_mesh(op, primitive, all_attributes, material_index=i)
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

    # TODO: Do we need this?
    for polygon in me.polygons:
        polygon.use_smooth = True

    me.update()

    return me
