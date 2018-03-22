import bpy
from mathutils import Matrix, Quaternion
from bpy_extras.io_utils import axis_conversion

"""
Handle nodes and scenes.

The glTF node forest is represented in Blender as objects. Since a glTF node
can have multiple optional components (mesh, camera, etc.) there is no
1:1 mapping between glTF nodes and Blender objects.

Hence, glTF nodes map to one or multiple Blender objects. glTF nodes without
a (supported) component map to an Empty object. A glTF mesh components maps
to a Blender object with mesh data, a glTF camera component map to an object
with camera data.

Transformations are appied as they appear in glTF, while a global scene root
object transforms the glTF space into Blender space.

TODO: Camera default orientations of glTF and Blender differ. This is currently
not taken into account. Hence, created cameras will not have the correct
orientation

TODO: Skin component is not supported
"""


def convert_matrix(m):
    """Converts a glTF matrix to a Blender matrix."""
    result = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    result.transpose()  # column-major to row-major
    return result


def convert_quaternion(q):
    """Converts a glTF quaternion to Blender a quaternion."""
    # xyzw -> wxyz
    return Quaternion([q[3], q[0], q[1], q[2]])


def set_transform(node, ob):
    if 'matrix' in node:
        m = node['matrix']
        m = convert_matrix(m)
        (loc, rot, sca) = m.decompose()
    else:
        sca = node.get('scale', [1.0, 1.0, 1.0])
        rot = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
        rot = convert_quaternion(rot)  # xyzw -> wxyz
        loc = node.get('translation', [0.0, 0.0, 0.0])

    ob.location = loc
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = rot
    ob.scale = sca


def create_node(op, idx):
    node = op.gltf['nodes'][idx]

    # print("Creating node: {}".format(idx) )

    def create(name, data):
        ob = bpy.data.objects.new(name, data)
        bpy.context.scene.objects.link(ob)
        return ob

    objects = []
    if 'mesh' in node:
        mesh_name = node.get('name', 'mesh[%d]' % idx)
        mesh = create(mesh_name, op.get_mesh(node['mesh']))
        objects.append(mesh)

    if 'camera' in node:
        camera_name = node.get('name', 'camera[%d]' % idx)
        camera = create(camera_name, op.get_camera(node['camera']))
        objects.append(camera)

    if not objects:
        name = node.get('name', 'node[%d]' % idx)
        objects.append(create(name, None))

    for obj in objects:
        set_transform(node, obj)

    parent = objects[0]
    children = node.get('children', [])
    for child_idx in children:
        for child_node in create_node(op, child_idx):
            child_node.parent = parent

    return objects


def find_root_idxs(op):
    nodes = op.gltf.get('nodes', [])
    idxs = set(range(0, len(nodes)))
    for node in nodes:
        for child_idx in node.get('children', []):
            idxs.remove(child_idx)
    root_idxs = list(idxs)
    return root_idxs


def create_root_objects(op, roots, scene):

    # Add a root object to fix the difference in orientation
    root_object = bpy.data.objects.new("SceneRoot", None)
    root_object.matrix_local = axis_conversion(
        from_forward="Z", from_up="Y").to_4x4()
    scene.objects.link(root_object)

    for root_idx in roots:
        # Link in any objects in this tree
        for ob in create_node(op, root_idx):
            ob.parent = root_object


def create_scenes(op):
    scenes = op.gltf.get('scenes', [])

    if not scenes:
        return False

    default_scene = op.gltf.get('scene', 0)

    for scene_idx, scene in enumerate(scenes):

        if scene_idx == default_scene:
            blender_scene = bpy.context.scene
            if 'name' in scene:
                blender_scene.name = scene.get('name')
        else:
            bpy.ops.scene.new(type='NEW')
            blender_scene = bpy.context.scene
            blender_scene.name = scene.get('name', 'scene[%d]' % scene_idx)

        op.scenes[scene_idx] = blender_scene
        blender_scene.render.engine = 'CYCLES'
        roots = scene.get('nodes', [])
        create_root_objects(op, roots, blender_scene)

    return True


def create_hierarchy(op):

    # A scene is not mandatory in glTF
    if not create_scenes(op):
        # Create scene from root nodes using active scene
        scene = bpy.context.scene
        roots = find_root_idxs(op)
        create_root_objects(op, roots, scene)
