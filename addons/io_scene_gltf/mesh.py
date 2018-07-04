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

    for kind, accessor_id in attributes.items():
        if kind == 'NORMAL':
            normals = op.get('accessor', accessor_id)
            for i, vertex in enumerate(me.vertices):
                vertex.normal = convert_coordinates(normals[i])

        if kind.startswith('COLOR_'):
            if kind not in me.vertex_colors.keys():
                me.vertex_colors.new(kind)
            rgba_layer = me.vertex_colors[kind].data
            colors = op.get('accessor', accessor_id)
            for polygon in me.polygons:
                for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                    color = colors[vert_idx]
                    if len(color) == 3: color.append(1.0) # Add alpha component
                    rgba_layer[loop_idx].color = colors[vert_idx]

        if kind.startswith('TEXCOORD_'):
            if kind not in me.uv_layers.keys():
                me.uv_textures.new(kind)

            uvs = op.get('accessor', accessor_id)
            uv_layer = me.uv_layers[kind].data
            for polygon in me.polygons:
                for vert_idx, loop_idx in zip(polygon.vertices, polygon.loop_indices):
                    uv = uvs[vert_idx]
                    uv_layer[loop_idx].uv = (uv[0], -uv[1])

            # Assign joints by generating vertex groups
        if kind.startswith('JOINTS_'):
            # Don't seem to need to deal with all_attributes here.
            # The only way I could find to set vertex groups was by
            # round-tripping through a bmesh.
            # TODO: find a better way?
            joints = op.get('accessor', accessor_id)
            weights = op.get('accessor', attributes['WEIGHTS_' + kind[len('JOINTS_'):]])
            bme = bmesh.new()
            bme.from_mesh(me)
            layer = bme.verts.layers.deform.new(kind)
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

    # TODO: Do we need this?
    for polygon in me.polygons:
        polygon.use_smooth = True

    me.update()

    return me
