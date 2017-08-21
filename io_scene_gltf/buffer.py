import base64
import os
import struct

def create_buffer(op, idx):
    buffer = op.gltf['buffers'][idx]

    if op.glb_buffer and idx == 0 and 'uri' not in buffer:
        return op.glb_buffer

    buffer_uri = buffer['uri']

    is_data_uri = buffer_uri[:37] == "data:application/octet-stream;base64,"
    if is_data_uri:
        return base64.b64decode(buffer_uri[37:])

    buffer_location = os.path.join(op.base_path, buffer_uri)
    print("Loading file", buffer_location)
    fp = open(buffer_location, "rb")
    bytes_read = fp.read()
    fp.close()

    return bytes_read


def create_buffer_view(op, idx):
    buffer_view = op.gltf['bufferViews'][idx]
    buffer = op.get_buffer(buffer_view["buffer"])
    byte_offset = buffer_view.get("byteOffset", 0)
    byte_length = buffer_view["byteLength"]
    result = buffer[byte_offset:byte_offset + byte_length]
    stride = buffer_view.get('byteStride', None)
    return (result, stride)


def create_accessor(op, idx):
    accessor = op.gltf['accessors'][idx]

    count = accessor['count']
    fmt_char_lut = dict([
        (5120, "b"), # BYTE
        (5121, "B"), # UNSIGNED_BYTE
        (5122, "h"), # SHORT
        (5123, "H"), # UNSIGNED_SHORT
        (5125, "I"), # UNSIGNED_INT
        (5126, "f")  # FLOAT
    ])
    fmt_char = fmt_char_lut[accessor['componentType']]
    component_size = struct.calcsize(fmt_char)
    num_components_lut = {
        "SCALAR": 1,
        "VEC2": 2,
        "VEC3": 3,
        "VEC4": 4,
        "MAT2": 4,
        "MAT3": 9,
        "MAT4": 16
    }
    num_components = num_components_lut[accessor['type']]
    fmt = "<" + (fmt_char * num_components)
    default_stride = struct.calcsize(fmt)

    # Special layouts for certain formats; see the section about
    # data alignment in the glTF 2.0 spec.
    if accessor['type'] == 'MAT2' and component_size == 1:
        fmt = "<" + \
            (fmt_char * 2) + "xx" + \
            (fmt_char * 2)
        default_stride = 8
    elif accessor['type'] == 'MAT3' and component_size == 1:
        fmt = "<" + \
            (fmt_char * 3) + "x" + \
            (fmt_char * 3) + "x" + \
            (fmt_char * 3)
        default_stride = 12
    elif accessor['type'] == 'MAT3' and component_size == 2:
        fmt = "<" + \
            (fmt_char * 3) + "xx" + \
            (fmt_char * 3) + "xx" + \
            (fmt_char * 3)
        default_stride = 24

    normalize = None
    if 'normalized' in accessor and accessor['normalized']:
        normalize_lut = dict([
            (5120, lambda x: max(x / (2**7 - 1), -1)), # BYTE
            (5121, lambda x: x / (2**8 - 1)), # UNSIGNED_BYTE
            (5122, lambda x: max(x / (2**15 - 1), -1)), # SHORT
            (5123, lambda x: x / (2**16 - 1)), # UNSIGNED_SHORT
            (5125, lambda x: x / (2**32 - 1)) # UNSIGNED_INT
        ])
        normalize = normalize_lut[accessor['componentType']]

    if 'bufferView' in accessor:
        (buf, stride) = op.get_buffer_view(accessor['bufferView'])
        stride = stride or default_stride
    else:
        stride = default_stride
        buf = [0] * (stride * count)

    if 'sparse' in accessor:
        #TODO sparse
        raise Exception("sparse accessors unsupported")

    off = accessor.get('byteOffset', 0)
    result = []
    while len(result) < count:
        elem = struct.unpack_from(fmt, buf, offset = off)
        if normalize:
            elem = tuple([normalize(x) for x in elem])
        if num_components == 1:
            elem = elem[0]
        result.append(elem)
        off += stride

    return result
