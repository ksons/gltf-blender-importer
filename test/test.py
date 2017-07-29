import bpy
import glob
import os

def run_tests(dir):
    successes = 0
    failures = 0
    failing_files = []

    files = (
        glob.glob(dir + '/**/*.gltf', recursive = True) +
        glob.glob(dir + '/**/*.glb', recursive = True)
    )
    for filename in files:
        print("\nTrying ", filename, "...")

        bpy.ops.wm.read_homefile()
        try:
            bpy.ops.import_scene.gltf(filepath = filename)
            successes += 1
            print("[SUCCESS]")
        except Exception as e:
            print("[FAILURE]")
            print("error: ", e)
            failures += 1
            failing_files.append(filename)

    num_files = len(files)
    print("\n\n==========")
    print("[%d/%d] successes" % (successes, num_files))
    print("[%d/%d] failures" % (failures, num_files))

    if failures > 0:
        print("\nThe failing files were: ")
        for filename in failing_files:
            print("    ", filename)    

def main():
    # Check for glTF importer
    try:
        bpy.ops.import_scene.gltf.get_instance()
    except:
        print("\n-----------")
        print("glTF importer not found")
        print("Check that add-on is installed and enabled")
        print("See README.md for instructions")
        return

    # Find sample directory
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    samples_dir = os.path.join(cur_dir, "glTF-Sample-Models/2.0/")
    if not os.path.isdir(samples_dir):
        print("\n-----------")
        print("glTF-Sample-Models/2.0/ not found")
        print("Get it by running `git submodule update --init --recursive`")
        print("See README.md for instructions")
        return

    run_tests(samples_dir)


main()
