import os
import json
import struct
from . import GLTF_VERSION, EXTENSIONS


def load(op):
    parse_file(op)
    check_version(op)
    check_extensions(op)


def parse_file(op):
    op.glb_buffer = None

    filename = op.filepath

    # Remember this for resolving relative paths
    op.base_path = os.path.dirname(filename)

    with open(filename, 'rb') as f:
        contents = f.read()

    # Use magic number to detect GLB files.
    is_glb = contents[:4] == b'glTF'
    if is_glb:
        parse_glb(op, contents)
    else:
        parse_gltf(op, contents)


def parse_gltf(op, contents):
    op.gltf = json.loads(contents.decode('utf-8'))


def parse_glb(op, contents):
    contents = memoryview(contents)

    # Parse the header
    header = struct.unpack_from('<4sII', contents)
    glb_version = header[1]
    if glb_version != 2:
        raise Exception('GLB: version not supported: %d' % glb_version)

    # Parse the chunks; we only want the JSON and BIN ones
    offset = 12  # end of header
    while offset < len(contents):
        length, type = struct.unpack_from('<I4s', contents, offset=offset)
        offset += 8
        data = contents[offset: offset + length]
        offset += length

        # The first chunk must be JSON
        if not hasattr(op, 'gltf'):
            assert(type == b'JSON')
            op.gltf = json.loads(
                data.tobytes().decode('utf-8'),  # Need to decode for < 2.79.4 which comes with Python 3.5
                encoding='utf-8'
            )
        else:
            if type == b'BIN\0':
                op.glb_buffer = data
                return
    else:
        raise Exception('empty GLB!')


def check_version(op):
    def parse_version(s):
        """Parse a string like '1.1' to a tuple (1,1)."""
        try:
            version = tuple(int(x) for x in s.split('.'))
            if len(version) >= 2:
                return version
        except Exception:
            pass
        raise Exception('unknown version format: %s' % s)

    asset = op.gltf['asset']

    if 'minVersion' in asset:
        min_version = parse_version(asset['minVersion'])
        supported = GLTF_VERSION >= min_version
        if not supported:
            raise Exception('unsupported minimum version: %s' % min_version)
    else:
        version = parse_version(asset['version'])
        # Check only major version; we should be backwards- and forwards-compatible
        supported = version[0] == GLTF_VERSION[0]
        if not supported:
            raise Exception('unsupported version: %s' % version)


def check_extensions(op):
    required = set(op.gltf.get('extensionsRequired', []))
    used = set(op.gltf.get('extensionsUsed', []))

    unsupported_required = required.difference(EXTENSIONS)
    for ext in unsupported_required:
        raise Exception('unsupported extension was required: %s' % ext)

    unsupported_used = list(used.difference(EXTENSIONS))
    if unsupported_used:
        print(
            'Note that the following extensions are unsupported:',
            *unsupported_used)
