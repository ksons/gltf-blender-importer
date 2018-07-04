import bpy
from mathutils import Matrix, Quaternion, Vector

# TODO: comment all this

def create_vforest(op):
    nodes = op.gltf.get('nodes', [])

    vnodes = []
    id_to_vnode = {}

    for id, node in enumerate(nodes):
        vnode = {
            'node_id': id,
            'name': node.get('name', 'nodes[%d]' % id),
            'parent': None,
            'children': [],
            'skeleton_root': None,
            'type': 'NORMAL',
            'trs': get_trs(node),
        }
        id_to_vnode[id] = vnode
        vnodes.append(vnode)

    # Fill in the parent/child relationships
    for id, node in enumerate(nodes):
        vnode = id_to_vnode[id]
        for child_id in node.get('children', []):
            child_vnode = id_to_vnode[child_id]
            child_vnode['parent'] = vnode
            vnode['children'].append(child_vnode)

    # Insert armatures for the skins
    skins = op.gltf.get('skins', [])
    for skin_id, skin in enumerate(skins):
        if 'skeleton' not in skin:
            raise Exception('unimplemented: skin missing skeleton attribute')
        skeleton_root_id = skin['skeleton']
        skeleton_root = id_to_vnode[skeleton_root_id]

        def insert_parent(vnode, parent):
            old_parent = vnode['parent']
            vnode['parent'] = parent
            parent['children'].append(vnode)
            if old_parent:
                pos = old_parent['children'].index(vnode)
                old_parent['children'][pos] = parent
                parent['parent'] = old_parent
            else:
                parent['parent'] = None

        armature = {
            'name': skin.get('name', 'skins[%d]' % skin_id),
            'children': [],
            'type': 'ARMATURE',
            'skin_id': skin_id,
            'parent': None,
        }
        vnodes.append(armature)
        insert_parent(skeleton_root, armature)

        def mark_containing_armature(vnode):
            if 'armature_vnode' in vnode:
                raise Exception('unsupported: a node (ID=%d) belongs to two different skins' % vnode['gltf_id'])
            vnode['armature_vnode'] = armature
            for child in vnode['children']: mark_containing_armature(child)

        mark_containing_armature(skeleton_root)

        for joint_node_id in skin['joints']:
            vnode = id_to_vnode[joint_node_id]
            vnode['type'] = 'BONE'

        # A curious fact is that bone positions in Blender are not specified
        # relative to their parent but relative to the containing armature. We
        # compute those matrices for each bone now.
        def compute_bone_mats(vnode, parent_mat=Matrix.Identity(4)):
            mat = parent_mat
            if 'trs' in vnode:
                mat = parent_mat * trs_to_matrix(vnode['trs'])
            if vnode['type'] == 'BONE':
                vnode['bone_matrix'] = mat
            for child in vnode['children']:
                compute_bone_mats(child, Matrix(mat))

        compute_bone_mats(armature)

    # Insert meshes
    for id, node in enumerate(nodes):
        if 'mesh' not in node: continue

        vnode = id_to_vnode[id]
        mesh_id = node['mesh']
        mesh = {
            'name': op.gltf['meshes'][mesh_id].get('name', 'meshes[%d]' % mesh_id),
            'children': [],
            'type': 'MESH',
            'mesh_id': mesh_id,
            'parent': vnode,
        }
        vnodes.append(mesh)
        vnode['children'].append(mesh)

    # TODO: cameras

    # Find the roots
    vnode_roots = [vnode for vnode in vnodes if not vnode['parent']]


    op.vnodes = vnodes
    op.vnode_roots = vnode_roots
    op.id_to_vnode = id_to_vnode


def realize_vforest(op):
    def realize_vnode(vnode):
        if vnode['type'] == 'NORMAL':
            ob = bpy.data.objects.new(vnode['name'], None)
            bpy.context.scene.objects.link(ob)
            vnode['blender_object'] = ob
            loc, rot, sca = vnode['trs']
            ob.location = loc
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = rot
            ob.scale = sca
            if vnode['parent']:
                ob.parent = vnode['parent']['blender_object']

        elif vnode['type'] == 'MESH':
            data = op.get('mesh', vnode['mesh_id'])
            ob = bpy.data.objects.new(vnode['name'], data)
            bpy.context.scene.objects.link(ob)
            vnode['blender_object'] = ob
            ob.parent = vnode['parent']['blender_object']

        elif vnode['type'] == 'ARMATURE':
            #armature = bpy.data.armatures.new(vnode['name'])
            #armature.show_x_ray = True
            #ob = bpy.data.objects.new(vnode['name'], armature)
            bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
            ob = bpy.context.object
            vnode['blender_armature'] = ob.data
            vnode['blender_object'] = ob
            if vnode['parent']:
                ob.parent = vnode['parent']['blender_object']

        elif vnode['type'] == 'BONE':
            armature = vnode['armature_vnode']['blender_armature']
            bone = armature.edit_bones.new(vnode['name'])
            bone.use_connect = False
            bone.head = vnode['bone_matrix'] * Vector((0, 0, 0))
            bone.tail = vnode['bone_matrix'] * Vector((0, 0, 1))
            vnode['blender_editbone'] = bone
            if vnode['parent'] and 'blender_editbone' in vnode['parent']:
                bone.parent = vnode['parent']['blender_editbone']

        else:
            assert(False)

        for child in vnode['children']:
            realize_vnode(child)

    for root in op.vnode_roots:
        realize_vnode(root)


def trs_to_matrix(trs):
    loc, rot, sca = trs
    m = Matrix.Identity(4)
    m[0][0] = sca[0]
    m[1][1] = sca[1]
    m[2][2] = sca[2]
    m = Quaternion(rot).to_matrix().to_4x4() * m
    m = Matrix.Translation(Vector(loc)) * m
    return m

def get_trs(node):
    if 'matrix' in node:
        m = node['matrix']
         # column-major to row-major
        m = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        m.transpose()
        (loc, rot, sca) = m.decompose()
    else:
        sca = node.get('scale', [1.0, 1.0, 1.0])
        rot = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
        rot = [rot[3], rot[0], rot[1], rot[2]] # xyzw -> wxyz
        loc = node.get('translation', [0.0, 0.0, 0.0])

    # Switch glTF coordinates to Blender coordinates
    sca = [sca[0], sca[2], sca[1]]
    rot = [rot[0], rot[1], -rot[3], rot[2]]
    loc = [loc[0], -loc[2], loc[1]]

    return (loc, rot, sca)



def create_node(op, idx):
    node = op.gltf['nodes'][idx]
    name = node.get('name', 'nodes[%d]' % idx)

    if 'mesh' in node and 'camera' in node:
        # Blender objects can't have >1 data item (I think?) so create some
        # dummy children to hold them
        ob = bpy.data.objects.new(name, None)
        mesh_ob = bpy.data.objects.new(
            name + '.mesh',
            op.get('mesh', node['mesh'])
        )
        camera_ob = bpy.data.objects.new(
            name + '.camera',
            op.get('camera', node['camera'])
        )
        mesh_ob.parent = ob
        camera_ob.parent = ob
    elif 'mesh' in node:
        ob = bpy.data.objects.new(name, op.get('mesh', node['mesh']))
    elif 'camera' in node:
        ob = bpy.data.objects.new(name, op.get('camera', node['camera']))
    else:
        ob = bpy.data.objects.new(name, None)

    set_transform(node, ob)

    for child_idx in node.get('children', []):
        op.get('node', child_idx).parent = ob

    return ob


def create_scene(op, idx):
    scene = op.gltf['scenes'][idx]
    name = scene.get('name', 'scene[%d]' % idx)
    scn = bpy.data.scenes.new(name)
    scn.render.engine = 'CYCLES'

    roots = scene.get('nodes', [])
    for root_idx in roots:
        def link_hierarchy(root):
            scn.objects.link(root)
            for child in root.children:
                link_hierarchy(child)
        link_hierarchy(op.get('node', root_idx))

    return scn

def create_scenes(op):
    create_vforest(op)
    realize_vforest(op)
    #for i in range(0, len(op.gltf.get('scenes', []))):
    #    create_scene(op, i)
