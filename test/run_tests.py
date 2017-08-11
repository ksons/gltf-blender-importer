#!/usr/bin/env python
"""Run and report on automated tests for the importer.

Calls Blender to run tests and generate a report.json file in this
directory with the results. Then prints the results. With the flag
--only-report, skips running the tests and prints the results from
an existing report.json file.

You can read the test results programmatically (eg. for CI) from the
report.json file or by examining the exit code of this script. Possible
values are:

0 - All tests passed
1 - Some kind of error occurred (as distinct from "some test failed")
3 - At least one test failed

"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


base_dir = os.path.dirname(os.path.abspath(__file__))
samples_path = os.path.join(base_dir, 'glTF-Sample-Models', '2.0')
report_path = os.path.join(base_dir, 'report.json')
test_script = os.path.join(base_dir, 'generate_report.py')
src_addon_dir = os.path.join(base_dir, os.pardir, 'io_scene_gltf')


def generate_report():
    """Calls Blender to generate report.json file."""
    if not os.path.isdir(samples_path):
        print("Couldn't find glTF-Sample-Models/2.0/")
        print("Get it by running `git submodule update --init --recursive`")
        print("See README.md for more instructions")
        print("Tests did not run")
        sys.exit(1)

    # Print Blender version for debugging
    try:
        subprocess.run(['blender', '--version'], check=True)
    except:
        print("Check that Blender is installed!")
        raise

    print()

    # We're going to try to run Blender in a clean-ish environment for
    # testing. We don't want to use whatever the user has installed for
    # the glTF importer addon because it might be old, etc; we want to
    # be sure we're using the current state of ../io_scene_gltf. So
    # create a new directory to use as scripts/addons/, symlink our
    # addon into it, and tell Blender to use that.
    with tempfile.TemporaryDirectory() as scripts_dir:
        addons_dir = os.path.join(scripts_dir, 'addons')
        os.mkdir(addons_dir)
        blender_addon_path = os.path.join(addons_dir, 'io_scene_gltf')
        os.symlink(src=src_addon_dir, dst=blender_addon_path)

        env = os.environ.copy()
        env['BLENDER_USER_SCRIPTS'] = scripts_dir
        #TODO Should we worry about BLENDER_SYSTEM_SCRIPTS, etc?

        subprocess.run(
            [
                'blender',
                '--background', # run UI-less
                '--factory-startup', # factory settings
                '--addons', 'io_scene_gltf', # enable the addon
                '--python', test_script # run the test script
            ],
            env=env,
            check=True
        )


def print_report():
    """Print report from report.json file.

    Exits with the appropriate exit code afterwards.

    """
    with open(report_path) as f:
        report = json.load(f)

    tests = report['tests']

    num_passed = 0
    num_failed = 0
    failures = []
    ok = '\033[32m' + 'ok' + '\033[0m' # green 'ok'
    failed = '\033[31m' + 'FAILED' + '\033[0m' # red 'FAILED'
    for test in tests:
        name = os.path.relpath(test['filename'], samples_path)
        print('import', name, '... ', end='')
        if test['result'] == 'PASSED':
            print(ok, "(%.4f s)" % test['timeElapsed'])
            num_passed += 1
        else:
            print(failed)
            print(test['error'])
            num_failed += 1
            failures.append(name)

    if failures:
        print('\nfailures:')
        for name in failures:
            print('   ', name)

    result = ok if num_failed == 0 else failed
    print(
        '\ntest result: %s. %d passed; %d failed\n' %
        (result, num_passed, num_failed)
    )

    exit_code = 0 if num_failed == 0 else 3
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser(description='Run glTF importer tests.')
    parser.add_argument('--only-report', action='store_true',
                        help='print last report (do not run tests)')
    args = parser.parse_args()

    if not args.only_report:
        generate_report()
    print_report()


main()
