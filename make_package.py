import os
import shutil
import tempfile


def make_package(suffix=None):
    this_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(this_dir, 'dist')

    if not os.path.exists(dist_dir):
        os.makedirs(dist_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        shutil.copytree(
            os.path.join(this_dir, 'addons', 'io_scene_gltf'),
            os.path.join(tmpdir, 'io_scene_gltf'),
            ignore=shutil.ignore_patterns('__pycache__'))

        zip_name = 'io_scene_gltf'
        if suffix:
            zip_name += '-' + suffix

        shutil.make_archive(
            os.path.join('dist', zip_name),
            'zip',
            tmpdir)


if __name__ == '__main__':
    make_package()
