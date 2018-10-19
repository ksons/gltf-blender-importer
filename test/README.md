## Testing


### Instructions

Just run

````
./test.py run
````

in this directory. The sample models are stored as a git submodule. The first
time you run this, it will automatically initialize submodules to get the sample
files (if needed).

### About

The [glTF Sample Models](https://github.com/KhronosGroup/glTF-Sample-Models)
are used for automated testing of the importer.

When you run the tests, the glTF-Sample-Models/2.0/ directory is recursively
searched to find .gltf and .glb files and then Blender tries to import
each one. If the importer doesn't raise an exception, this counts as the
test having "passed" :)

The results of the tests will be printed out: you should get a green "ok" if
everything's good. They are also written to a JSON file in this directory
called report.json. You can use this file or the exit code of run_tests.py
to determine if the tests passed in a script.

Call `./test.py -h` for more help.
