import base64, os, struct

# This file handles creating buffers, buffer views, and accessors. It's pure
# python and doesn't depend on Blender at all.
#
# Buffers and buffer views are represented with memoryviews so we can do
# efficient slicing.


def create_buffer(op, idx):
    """Create a memoryview for buffers[idx]."""
    buffer = op.gltf['buffers'][idx]

    # Handle GLB buffer
    if op.glb_buffer != None and idx == 0 and 'uri' not in buffer:
        return op.glb_buffer

    uri = buffer['uri']

    # Try to decode base64 data URIs
    if uri.startswith('data:'):
        idx = uri.find(';base64,')
        if idx != -1:
            base64_data = uri[idx + len(';base64,'):]
            return memoryview(base64.b64decode(base64_data))

    # If we got here, assume it's a filepath
    buffer_location = os.path.join(op.base_path, uri)  # TODO: absolute paths?
    with open(buffer_location, 'rb') as fp:
        return memoryview(fp.read())


def create_buffer_view(op, idx):
    """Create a pair for bufferViews[idx].

    The pair contains a memoryview for the view and also its stride, which is
    specified in the bufferView as well.
    """
    buffer_view = op.gltf['bufferViews'][idx]
    buffer = op.get('buffer', buffer_view['buffer'])
    byte_offset = buffer_view.get('byteOffset', 0)
    byte_length = buffer_view['byteLength']
    stride = buffer_view.get('byteStride', None)

    view = buffer[byte_offset:byte_offset + byte_length]
    return (view, stride)


def create_accessor(op, idx):
    """Create an array holding the elements of accessors[idx].

    If the accessor is of SCALAR type, each element is a number. Otherwise, each
    element is a tuple holding the components for that element.
    """
    accessor = op.gltf['accessors'][idx]
    return create_accessor_from_properties(op, accessor)


def create_accessor_from_properties(op, accessor):
    count = accessor['count']
    fmt_char_lut = dict([
        (5120, 'b'),  # BYTE
        (5121, 'B'),  # UNSIGNED_BYTE
        (5122, 'h'),  # SHORT
        (5123, 'H'),  # UNSIGNED_SHORT
        (5125, 'I'),  # UNSIGNED_INT
        (5126, 'f')   # FLOAT
    ])
    fmt_char = fmt_char_lut[accessor['componentType']]
    component_size = struct.calcsize(fmt_char)
    num_components_lut = {
        'SCALAR': 1,
        'VEC2': 2,
        'VEC3': 3,
        'VEC4': 4,
        'MAT2': 4,
        'MAT3': 9,
        'MAT4': 16
    }
    num_components = num_components_lut[accessor['type']]
    fmt = '<' + (fmt_char * num_components)
    default_stride = struct.calcsize(fmt)

    # Special layouts for certain formats; see the section about
    # data alignment in the glTF 2.0 spec.
    if accessor['type'] == 'MAT2' and component_size == 1:
        fmt = '<' + \
            (fmt_char * 2) + 'xx' + \
            (fmt_char * 2)
        default_stride = 8
    elif accessor['type'] == 'MAT3' and component_size == 1:
        fmt = '<' + \
            (fmt_char * 3) + 'x' + \
            (fmt_char * 3) + 'x' + \
            (fmt_char * 3)
        default_stride = 12
    elif accessor['type'] == 'MAT3' and component_size == 2:
        fmt = '<' + \
            (fmt_char * 3) + 'xx' + \
            (fmt_char * 3) + 'xx' + \
            (fmt_char * 3)
        default_stride = 24

    normalize = None
    if 'normalized' in accessor and accessor['normalized']:
        normalize_lut = dict([
            (5120, lambda x: max(x / (2**7 - 1), -1)),   # BYTE
            (5121, lambda x: x / (2**8 - 1)),            # UNSIGNED_BYTE
            (5122, lambda x: max(x / (2**15 - 1), -1)),  # SHORT
            (5123, lambda x: x / (2**16 - 1)),           # UNSIGNED_SHORT
            (5125, lambda x: x / (2**32 - 1))            # UNSIGNED_INT
        ])
        normalize = normalize_lut[accessor['componentType']]

    if 'bufferView' in accessor:
        (buf, stride) = op.get('buffer_view', accessor['bufferView'])
        stride = stride or default_stride
    else:
        stride = default_stride
        buf = b'\0' * (stride * count)


    # Main decoding loop
    off = accessor.get('byteOffset', 0)
    result = []
    while len(result) != count:
        elem = struct.unpack_from(fmt, buf, offset=off)
        result.append(elem)
        off += stride
    if normalize:
        for i in range(0, count):
            result[i] = tuple([normalize(x) for x in result[i]])
    if num_components == 1:
        for i in range(0, count):
            result[i] = result[i][0]


    # A sparse property says "change the elements at these indices to these
    # values" where "these" are given in an accessor-like way, so we find the
    # list of indices and values by recursing into this function.
    if 'sparse' in accessor:
        sparse = accessor['sparse']
        indices_props = {
            'count': sparse['count'],
            'bufferView': sparse['indices']['bufferView'],
            'byteOffset': sparse['indices'].get('byteOffset', 0),
            'componentType': sparse['indices']['componentType'],
            'type': 'SCALAR',
        }
        indices = create_accessor_from_properties(op, indices_props)
        values_props = {
            'count': sparse['count'],
            'bufferView': sparse['values']['bufferView'],
            'byteOffset': sparse['values'].get('byteOffset', 0),
            'componentType': accessor['componentType'],
            'type': accessor['type'],
            'normalized': accessor.get('normalized', False),
        }
        values = create_accessor_from_properties(op, values_props)

        for (index, val) in zip(indices, values):
            result[index] = val

    return result
