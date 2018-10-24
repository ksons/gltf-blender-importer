import argparse
import os
import re
import subprocess

import make_package


def replace_in_file(file, expr, new_substr):
    lines = []
    regex = re.compile(expr, re.IGNORECASE)
    with open(file) as infile:
        for line in infile:
            line = regex.sub(new_substr, line)
            lines.append(line)
    with open(file, 'w') as outfile:
        for line in lines:
            outfile.write(line)


this_dir = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument('version')
args = parser.parse_args()

version = args.version.split('.')
version_string = '.'.join(version)
version_tuple = '(%s)' % ', '.join(version)

main_file = os.path.join(this_dir, 'addons', 'io_scene_gltf', '__init__.py')
readme_file = os.path.join(this_dir, 'README.md')

replace_in_file(main_file,
                r"'version': \([0-9\, ]+\)",
                "'version': {}".format(version_tuple))

replace_in_file(readme_file,
                r'download/v[0-9\.]+/io_scene_gltf-[0-9\.]+.zip',
                'download/v{}/io_scene_gltf-{}.zip'.format(version_string, version_string))

os.chdir(this_dir)
subprocess.call(['git', 'add', main_file, readme_file])
subprocess.call(['git', 'commit', '-m', 'Bump version number to {}'.format(version_string)])
subprocess.call(['git', 'tag', 'v{}'.format(version_string)])

make_package.make_package(suffix=version_string)
