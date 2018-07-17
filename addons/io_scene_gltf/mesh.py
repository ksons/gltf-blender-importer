import bmesh
import bpy


def convert_coordinates(v):
    """Convert glTF coordinate system to Blender."""
    return [v[0], -v[2], v[1]]


def primitive_to_mesh(op, primitive, name, layers, material_index):
    """Create a Blender mesh for a glTF primitive."""

    attributes = primitive['attributes']

    me = bpy.data.meshes.new(name)

    # Early out if there's no POSITION data
    if 'POSITION' not in attributes:
        return me

    verts = op.get('accessor', attributes['POSITION'])
    verts = [convert_coordinates(v) for v in verts]
    edges = []
    faces = []


    # Generate the topology

    mode = primitive.get('mode', 4)

    if 'indices' in primitive:
        indices = op.get('accessor', primitive['indices'])
    else:
        indices = range(0, len(verts))

    # TODO: only mode TRIANGLES is tested!!
    if mode == 0:
        # POINTS
        pass
    elif mode == 1:
        # LINES
        #   1   3
        #  /   /
        # 0   2
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices), 2)]
    elif mode == 2:
        # LINE LOOP
        #   1---2
        #  /     \
        # 0-------3
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices) - 1)]
        edges.append((indices[-1], indices[0]))
    elif mode == 3:
        # LINE STRIP
        #   1---2
        #  /     \
        # 0       3
        edges = [tuple(indices[i:i+2]) for i in range(0, len(indices) - 1)]
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
        raise Exception('primitive mode unimplemented: %d' % mode)

    me.from_pydata(verts, edges, faces)
    me.validate()


    # Assign material to each poly
    for polygon in me.polygons:
        polygon.material_index = material_index


    # Create the caller's requested layers; any layers needed by the attributes
    # for this mesh will also be created, if they weren't created here, below.
    for layer, names in layers.items():
        for name in names:
            if layer == 'vertex_colors': me.vertex_colors.new(name)
            if layer == 'uv_layers': me.uv_textures.new(name)

    if 'NORMAL' in attributes:
        normals = op.get('accessor', attributes['NORMAL'])
        for i, vertex in enumerate(me.vertices):
            vertex.normal = convert_coordinates(normals[i])

    k = 0
    while 'COLOR_%d' % k in attributes:
        layer_name = 'COLOR_%d' % k
        if layer_name not in me.vertex_colors.keys():
            me.vertex_colors.new(layer_name)
        rgba_layer = me.vertex_colors[layer_name].data
        colors = op.get('accessor', attributes[layer_name])

        # Old Blender versions only take RGB and new ones only take RGBA
        if bpy.app.version >= (2, 79, 4): # this bound is not necessarily tight
            if colors and len(colors[0]) == 3:
                colors = [color+[1] for color in colors]
        else:
            if colors and len(colors[0]) == 4:
                print("your Blender version doesn't support RGBA vertex colors. Upgrade!")
                colors = [color[:3] for color in colors]

        for polygon in me.polygons:
            for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                rgba_layer[loop_idx].color = colors[vert_idx]
        k += 1

    k = 0
    while 'TEXCOORD_%d' % k in attributes:
        layer_name = 'TEXCOORD_%d' % k
        if layer_name not in me.uv_layers.keys():
            me.uv_textures.new(layer_name)
        uvs = op.get('accessor', attributes[layer_name])
        uv_layer = me.uv_layers[layer_name].data
        for polygon in me.polygons:
            for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                uv = uvs[vert_idx]
                uv_layer[loop_idx].uv = (uv[0], 1 - uv[1])
        k += 1


    # Assign joints/weights. We begin by collecting all the sets (multiple sets
    # allow for >4 joint influences).
    # TODO: multiple sets are untested!!
    joint_sets = []
    weight_sets = []
    k = 0
    while 'JOINTS_%d' % k in attributes and 'WEIGHTS_%d' % k in attributes:
        joint_sets.append(op.get('accessor', attributes['JOINTS_%d' % k]))
        weight_sets.append(op.get('accessor', attributes['WEIGHTS_%d' % k]))
        k += 1
    if joint_sets:
        # Now create vertex groups. The only way I could find to set vertex
        # groups was by round-tripping through a bmesh.
        # TODO: find a better way?
        bme = bmesh.new()
        bme.from_mesh(me)
        layer = bme.verts.layers.deform.new('Vertex Weights')
        for i, vert in enumerate(bme.verts):
            for joint_set, weight_set in zip(joint_sets, weight_sets):
                for j in range(0, 4):
                    if weight_set[i][j] != 0:
                        vert[layer][joint_set[i][j]] = weight_set[i][j]
        bme.to_mesh(me)
        bme.free()


    me.update()

    return me


def create_mesh(op, idx):
    mesh = op.gltf['meshes'][idx]
    name = mesh.get('name', 'meshes[%d]' % idx)
    primitives = mesh['primitives']

    # We'll create temporary meshes for each primitive and merge them using
    # bmesh.

    # When we merge a mesh with eg. a vertex color layer with one without into
    # the same bmesh, Blender will drop the vertex color layer. Therefore we
    # make a pass over the primitives here collecting a list of all the layers
    # we'll need so we can request they be created for each temporary mesh.
    layers = {
        'vertex_colors': set(),
        'uv_layers': set(),
    }
    for primitive in primitives:
        for kind, accessor_id in primitive['attributes'].items():
            if kind.startswith('COLOR_'):
                layers['vertex_colors'].add(kind)
            if kind.startswith('TEXCOORD_'):
                layers['uv_layers'].add(kind)

    # Also, if any of the materials used in this mesh use COLOR_0 attributes, we
    # need to request that that layer be created; else the Attribute node
    # referencing COLOR_0 in those materials will produce a solid red color. See
    # material.compute_materials_using_color0, which, note,  must be called
    # before this function.
    use_color0 = any(
        prim.get('material', 'default_material') in op.materials_using_color0
        for prim in primitives
    )
    if use_color0:
        layers['vertex_colors'].add('COLOR_0')

    # Make a list of all the materials this mesh will need; the material on a
    # poly is set by giving an index into this list.
    materials = list(set(
        op.get('material', primitive.get('material', 'default_material'))
        for primitive in primitives
    ))

    bme = bmesh.new()
    for i, primitive in enumerate(mesh['primitives']):
        blender_material = op.get('material', primitive.get('material', 'default_material'))
        tmp_mesh = primitive_to_mesh(
            op,
            primitive,
            name=name + '.primitives[i]',
            layers=layers,
            material_index=materials.index(blender_material)
        )
        bme.from_mesh(tmp_mesh)
        bpy.data.meshes.remove(tmp_mesh)
    me = bpy.data.meshes.new(name)
    bme.to_mesh(me)
    bme.free()

    # Fill in the material list (we can't do me.materials = materials since this
    # property is read-only).
    for material in materials:
        me.materials.append(material)

    if op.smooth_polys:
        for polygon in me.polygons:
            polygon.use_smooth = True

    me.update()

    return me
