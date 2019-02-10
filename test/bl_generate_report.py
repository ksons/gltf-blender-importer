"""
Runs tests and writes the results to the report.json file.

This should be executed inside Blender, not from normal Python!
"""

import glob
import json
import os
from timeit import default_timer as timer
import sys

import bpy

print('bpy.app.version:', bpy.app.version)
print('python sys.version:', sys.version)

base_dir = os.path.dirname(os.path.abspath(__file__))
samples_path = os.path.join(base_dir, 'glTF-Sample-Models', '2.0')
site_local_path = os.path.join(base_dir, 'site_local')
report_path = os.path.join(base_dir, 'report.json')

tests = []

files = (
    glob.glob(samples_path + '/**/*.gltf', recursive=True) +
    glob.glob(samples_path + '/**/*.glb', recursive=True) +
    glob.glob(site_local_path + '/**/*.glb', recursive=True) +
    glob.glob(site_local_path + '/**/*.glb', recursive=True)
)

# Skip Draco encoded files for now
files = [fn for fn in files if 'Draco' not in fn]

for filename in files:
    short_name = os.path.relpath(filename, samples_path)
    print('\nTrying ', short_name, '...')

    bpy.ops.wm.read_factory_settings()

    try:
        start_time = timer()
        bpy.ops.import_scene.gltf_ksons(filepath=filename)
        end_time = timer()
        print('[PASSED]\n')
        test = {
            'filename': short_name,
            'result': 'PASSED',
            'timeElapsed': end_time - start_time,
        }

    except Exception as e:
        print('[FAILED]\n')
        test = {
            'filename': filename,
            'result': 'FAILED',
            'error': str(e),
        }

    tests.append(test)

report = {
    'blenderVersion': list(bpy.app.version),
    'tests': tests,
}

with open(report_path, 'w+') as f:
    json.dump(report, f, indent=4)
