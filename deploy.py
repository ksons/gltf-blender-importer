import argparse
import os
import sys
import re
import subprocess
import shutil

parser = argparse.ArgumentParser()
parser.add_argument("version")

args = parser.parse_args()
pathname = os.path.dirname(sys.argv[0])   


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


version = args.version.split('.')
version_string = ".".join(version)

main_file = os.path.join(pathname, 'addons', 'io_scene_gltf', '__init__.py')

replace_in_file(main_file,
                '\'version\': \([0-9\, ]*\)',
                '\'version\': (%s)' % ', '.join(version))


subprocess.call(["git", "add", main_file])
subprocess.call(["git", "commit", "-m", "Bumb version number to {}".format(version_string)])
subprocess.call(["git", "tag", "v{}".format(version_string)])

if not os.path.exists('dist'):
    os.makedirs('dist')
shutil.make_archive('dist/io_scene_gltf-{}'.format(version_string), 'zip',
                    'addons')
