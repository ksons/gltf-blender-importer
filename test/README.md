## Testing


### Instructions

1. Get the glTF sample models by initializing git submodules

    ````
    $ git submodule update --init --recursive
    ````

2. Run the tests with

    ````
    $ python run_tests.py
    ````


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

Call `python run_tests.py -h` for more help.
