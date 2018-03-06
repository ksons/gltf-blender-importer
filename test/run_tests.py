#!/usr/bin/env python
"""Run and report on automated tests for the importer.

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


base_dir = os.path.dirname(os.path.abspath(__file__))
samples_path = os.path.join(base_dir, 'glTF-Sample-Models', '2.0')
report_path = os.path.join(base_dir, 'report.json')
test_script = os.path.join(base_dir, 'generate_report.py')
scripts_dir = os.path.join(base_dir, os.pardir)


def fetch_samples():
    """Get sample files by initializing git submodules.
    """
    try:
        print("Checking if we're in a git repo...")
        subprocess.run(
            ['git', 'rev-parse'],
            cwd=base_dir,
            check=True
        )
    except BaseException:
        print('Is git installed?')
        print('Did you get this repo through git (as opposed to eg. a zip)?')
        raise

    try:
        print("Initializing submodules (be patient)...")
        subprocess.run(
            ['git', 'submodule', 'update', '--init', '--recursive'],
            cwd=base_dir,
            check=True
        )
    except BaseException:
        print("Couldn't init submodules. Aborting")
        raise

    if not os.path.isdir(samples_path):
        print("Samples still aren't there! Aborting")
        raise Exception('no samples after initializing submodules')
    else:
        print('Good to go!')
        print('This step should only happen once.\n\n')


def generate_report():
    """Calls Blender to generate report.json file.
    """
    if not os.path.isdir(samples_path):
        print("Couldn't find glTF-Sample-Models/2.0/")
        print("I'll try to fetch it for you...")
        fetch_samples()

    # Print Blender version for debugging
    try:
        subprocess.run(['blender', '--version'], check=True)
    except BaseException:
        print('Check that Blender is installed!')
        raise

    print()

    # We're going to try to run Blender in a clean-ish environment for
    # testing. we want to be sure we're using the current state of
    # 'io_scene_gltf'. The user scripts variable expects an addons/plugin
    # directory structure which we have in the projects root directory
    env = os.environ.copy()
    env['BLENDER_USER_SCRIPTS'] = scripts_dir
    # TODO: Should we worry about BLENDER_SYSTEM_SCRIPTS, etc?

    subprocess.run(
        [
            'blender',
            '-noaudio',  # sound ssystem to None (less output on stdout)
            '--background',  # run UI-less
            '--factory-startup',  # factory settings
            '--addons', 'io_scene_gltf',  # enable the addon
            '--python', test_script  # run the test script
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
    ok = '\033[32m' + 'ok' + '\033[0m'  # green 'ok'
    failed = '\033[31m' + 'FAILED' + '\033[0m'  # red 'FAILED'

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


def print_times():
    """Prints the tests sorted by import time."""
    with open(report_path) as f:
        report = json.load(f)

    def test_passed(test): return test['result'] == 'PASSED'
    tests = list(filter(test_passed, report['tests']))
    tests.sort(key=lambda test: test['timeElapsed'], reverse=True)

    for (num, test) in enumerate(tests, start=1):
        name = os.path.relpath(test['filename'], samples_path)
        print('( #%-3d )  % 2.4fs   %s' % (num, test['timeElapsed'], name))


parser = argparse.ArgumentParser(description='Run glTF importer tests.')
parser.add_argument(
    '--print-last-report',
    action='store_true',
    help="print last report (don't run tests again)",
)
parser.add_argument(
    '--print-last-times',
    action='store_true',
    help="show last results sorted by import time (don't run tests again)",
)
args = parser.parse_args()

if args.print_last_times:
    print_times()
elif args.print_last_report:
    print_report()
else:
    generate_report()
    print_report()
