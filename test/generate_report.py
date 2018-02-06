"""Runs importer tests in Blender and generates report file.

This script tests the glTF importer by trying to load the glTF
sample files. It writes a report about the test results to the
file report.json in the same directory as this script.

This script is designed to be called from run_tests.py. You
probably don't want to try running it on its own.

"""

import glob
import json
import os
from timeit import default_timer as timer

import bpy


base_dir = os.path.dirname(os.path.abspath(__file__))
samples_path = os.path.join(base_dir, 'glTF-Sample-Models/2.0/')
report_path = os.path.join(base_dir, 'report.json')


def run_tests():
    report = { 'tests': [] }
    tests = report['tests']

    files = (
        glob.glob(samples_path + '/**/*.gltf', recursive=True) +
        glob.glob(samples_path + '/**/*.glb', recursive=True)
    )
    for filename in files:
        print("\nTrying ", filename, "...")

        bpy.ops.wm.read_factory_settings()
        try:
            start_time = timer()
            bpy.ops.import_scene.gltf(filepath=filename)
            end_time = timer()
            print('[PASSED]\n')

            test = {
                'filename': filename,
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

    return report


def main():
    report = run_tests()
    with open(report_path, "w+") as report_file:
        json.dump(report, report_file, indent=4)


main()
