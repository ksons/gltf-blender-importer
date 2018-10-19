import tempfile
import os
import base64
import bpy
from bpy_extras.image_utils import load_image


def create_image(op, idx):
    image = op.gltf['images'][idx]

    img = None
    if 'uri' in image:
        uri = image['uri']
        is_data_uri = uri[:5] == 'data:'
        if is_data_uri:
            found_at = uri.find(';base64,')
            if found_at == -1:
                print('error loading image: data URI not base64?')
                return None
            else:
                buffer = base64.b64decode(uri[found_at + 8:])
        else:
            # Load the image from disk
            image_location = os.path.join(op.base_path, uri)
            img = load_image(image_location)
    else:
        buffer, _stride = op.get('buffer_view', image['bufferView'])

    if not img:
        # The image data is in buffer, but I don't know how to load an image
        # from memory. We'll write it to a temp file and load it from there.
        # Yes, this is a hack :)
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = os.path.join(tmpdir, 'image_%d' % idx)
            with open(img_path, 'wb') as f:
                f.write(buffer)
            img = load_image(img_path)
            img.pack()  # TODO: should we use as_png?

    img.name = image.get('name', 'images[%d]' % idx)

    return img
