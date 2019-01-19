import bmesh
import bpy
from mathutils import Vector


def create_mesh(op, idx):
    mesh = op.gltf['meshes'][idx]
    primitives = mesh['primitives']

    bme = bmesh.new()

    # If any of the materials used in this mesh use COLOR_0 attributes, we need
    # to pre-emptively create that layer, or else the Attribute node referencing
    # COLOR_0 in those materials will produce a solid red color. See
    # material.compute_materials_using_color0, which, note, must be called
    # before this function.
    needs_color0 = any(
        prim.get('material', 'default_material') in op.materials_using_color0
        for prim in primitives
    )
    if needs_color0:
        bme.loops.layers.color.new('COLOR_0')

    # Make a list of all the materials this mesh will need; the material on a
    # face is set by giving an index into this list.
    materials = list(set(
        op.get('material', primitive.get('material', 'default_material'))
        for primitive in primitives
    ))

    # Add in all the primitives
    for i, primitive in enumerate(mesh['primitives']):
        material = op.get('material', primitive.get('material', 'default_material'))
        material_idx = materials.index(material)

        add_in_primitive(op, bme, primitive, material_idx)

    name = mesh.get('name', 'meshes[%d]' % idx)
    me = bpy.data.meshes.new(name)
    bmesh_to_mesh(bme, me)
    bme.free()

    # Fill in the material list (we can't do me.materials = materials since this
    # property is read-only).
    for material in materials:
        me.materials.append(material)

    # Set polygon smoothing if the user requested it
    if op.smooth_polys:
        for polygon in me.polygons:
            polygon.use_smooth = True

    me.update()

    if not me.shape_keys:
        return me
    else:
        # Tell op.get not to cache us if we have morph targets; this is because
        # morph target weights are stored on the mesh instance in glTF, what
        # would be on the object in Blender. But in Blender shape keys are part
        # of the mesh. So when an object wants a mesh with morph targets, it
        # always needs to get a new one. Ergo we lose sharing for meshes with
        # morph targets.
        return {
            'result': me,
            'do_not_cache_me': True,
        }


def bmesh_to_mesh(bme, me):
    bme.to_mesh(me)

    if len(bme.verts.layers.shape) != 0:
        # The above does NOT create shape keys so if there's shape data we'll
        # have to do it by hand. The only way I could find to create a shape key
        # was to temporarily parent me to an object and use obj.shape_key_add.
        dummy_ob = bpy.data.objects.new('##dummy-object##', me)
        dummy_ob.shape_key_add('Basis')
        me.shape_keys.name = me.name
        for layer_name in bme.verts.layers.shape.keys():
            dummy_ob.shape_key_add(layer_name)
            key_block = me.shape_keys.key_blocks[layer_name]
            layer = bme.verts.layers.shape[layer_name]

            for i, v in enumerate(bme.verts):
                key_block.data[i].co = v[layer]

        bpy.data.objects.remove(dummy_ob)


def convert_coordinates(v):
    """Convert glTF coordinate system to Blender."""
    return [v[0], -v[2], v[1]]


def get_layer(bme_layers, name):
    """Gets a layer from a BMLayerCollection, creating it if it does not exist."""
    if name not in bme_layers:
        return bme_layers.new(name)
    return bme_layers[name]


def add_in_primitive(op, bme, primitive, material_index):
    """Adds the data for a glTF primitive into a bmesh."""
    attributes = primitive['attributes']

    # Early out if there's no POSITION data
    if 'POSITION' not in attributes:
        return
    positions = op.get('accessor', attributes['POSITION'])

    if 'indices' in primitive:
        indices = op.get('accessor', primitive['indices'])
    else:
        indices = range(0, len(positions))

    # Every primitive adds in a set of vertices to the bmesh. Each vertex has an
    # index in the bme.verts array, its bl_idx, and another in the arrays of
    # primitive attributes, its prim_idx.
    #
    # bl2prim contains pairs (bl_idx, prim_idx) for every vertex we'll add in,
    # ordered by bl_idx (the bl_idxs form a contiguous interval).
    #
    # Note that only vertices that show up the indices array actually get put
    # into the mesh and thus have a bl_idx! See #27.
    bl2prim = []
    used_prim_idxs = set(indices)
    bl_idx = len(bme.verts)
    for prim_idx in range(0, len(positions)):
        if prim_idx in used_prim_idxs:
            bl2prim.append((bl_idx, prim_idx))
            bl_idx += 1

    # Generate the topology (in terms of prim_idxs)
    mode = primitive.get('mode', 4)
    edges, tris = edges_and_tris(indices, mode)

    # verts is a list of the positions of the vertices we'll add in.
    verts = [
        convert_coordinates(positions[prim_idx])
        for bl_idx, prim_idx in bl2prim
    ]
    # We need to gives edges and faces in terms of indices into verts.
    # First build a table mapping prim_idxs to vert_idxs.
    prim2vert = [-1] * len(positions)
    first_bl_idx = len(bme.verts)
    for bl_idx, prim_idx in bl2prim:
        vert_idx = bl_idx - first_bl_idx
        prim2vert[prim_idx] = vert_idx
    vert_edges = [tuple(prim2vert[x] for x in y) for y in edges]
    vert_tris = [tuple(prim2vert[x] for x in y) for y in tris]

    # Finally create a tmp mesh with all our vertices.
    tmp_mesh = bpy.data.meshes.new('##tmp-mesh##')
    tmp_mesh.from_pydata(verts, vert_edges, vert_tris)
    tmp_mesh.validate()

    faces_off = len(bme.faces)

    # Add everything to the bmesh.
    bme.from_mesh(tmp_mesh)
    bpy.data.meshes.remove(tmp_mesh)
    bme.verts.ensure_lookup_table()
    bme.faces.ensure_lookup_table()

    # Set the material index on the faces we just added.
    for i in range(faces_off, len(bme.faces)):
        bme.faces[i].material_index = material_index

    # Set normals
    if 'NORMAL' in attributes:
        normals = op.get('accessor', attributes['NORMAL'])
        for bl_idx, prim_idx in bl2prim:
            bme.verts[bl_idx].normal = convert_coordinates(normals[prim_idx])

    # Set vertex colors
    k = 0
    while 'COLOR_%d' % k in attributes:
        layer_name = 'COLOR_%d' % k
        layer = get_layer(bme.loops.layers.color, layer_name)

        colors = op.get('accessor', attributes[layer_name])

        # Old Blender versions only take RGB and new ones only take RGBA
        if bpy.app.version >= (2, 79, 4):  # this bound is not necessarily tight
            if colors and len(colors[0]) == 3:
                colors = [color+(1,) for color in colors]
        else:
            if colors and len(colors[0]) == 4:
                print("Your Blender version doesn't support RGBA vertex colors. Upgrade!")
                colors = [color[:3] for color in colors]

        for bl_idx, prim_idx in bl2prim:
            for loop in bme.verts[bl_idx].link_loops:
                loop[layer] = colors[prim_idx]

        k += 1

    # Set texcoords
    k = 0
    while 'TEXCOORD_%d' % k in attributes:
        layer_name = 'TEXCOORD_%d' % k
        layer = get_layer(bme.loops.layers.uv, layer_name)

        uvs = op.get('accessor', attributes[layer_name])

        for bl_idx, prim_idx in bl2prim:
            # UV transform
            u, v = uvs[prim_idx]
            uv = (u, 1 - v)

            for loop in bme.verts[bl_idx].link_loops:
                loop[layer].uv = uv

        k += 1

    # Set joints/weights for skinning (multiple sets allow > 4 influences)
    # TODO: multiple sets are untested!
    joint_sets = []
    weight_sets = []
    k = 0
    while 'JOINTS_%d' % k in attributes and 'WEIGHTS_%d' % k in attributes:
        joint_sets.append(op.get('accessor', attributes['JOINTS_%d' % k]))
        weight_sets.append(op.get('accessor', attributes['WEIGHTS_%d' % k]))
        k += 1
    if joint_sets:
        layer = get_layer(bme.verts.layers.deform, 'Vertex Weights')

        for joint_set, weight_set in zip(joint_sets, weight_sets):
            for bl_idx, prim_idx in bl2prim:
                for j in range(0, 4):
                    weight = weight_set[prim_idx][j]
                    if weight != 0.0:
                        joint = joint_set[prim_idx][j]
                        bme.verts[bl_idx][layer][joint] = weight

    # Set morph target positions (we don't handle normals/tangents)
    for k, target in enumerate(primitive.get('targets', [])):
        if 'POSITION' not in target:
            continue

        layer = get_layer(bme.verts.layers.shape, 'Morph %d' % k)

        morph_positions = op.get('accessor', target['POSITION'])

        for bl_idx, prim_idx in bl2prim:
            bme.verts[bl_idx][layer] = convert_coordinates(
                Vector(positions[prim_idx]) +
                Vector(morph_positions[prim_idx])
            )


def edges_and_tris(indices, mode):
    edges = []
    tris = []
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
        tris = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]
    elif mode == 5:
        # TRIANGLE STRIP
        #   1---3---5
        #  / \ / \ /
        # 0---2---4
        def alternate(i, xs):
            ccw = i % 2 != 0
            return xs if ccw else (xs[0], xs[2], xs[1])
        tris = [
            alternate(i, tuple(indices[i:i+3]))
            for i in range(0, len(indices) - 2)
        ]
    elif mode == 6:
        # TRIANGLE FAN
        #   3---2
        #  / \ / \
        # 4---0---1
        tris = [
            (indices[0], indices[i], indices[i+1])
            for i in range(1, len(indices) - 1)
        ]
    else:
        raise Exception('primitive mode unimplemented: %d' % mode)

    return edges, tris
