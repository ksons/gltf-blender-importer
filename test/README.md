## Testing

### Instructions

1. Ensure the glTF Importer is installed and enabled in Blender.

2. Get the glTF samples by initializing git submodules

    ````
    git submodule update --init --recursive
    ````

3. Run the tests with

    ````
    blender -b --python test.py
    ````

-----

The glTF-Sample-Models/2.0/ directory will be recursively searched for
.gltf and .glb files and each will be loaded. When the tests are finished
the number of files successfully loaded and any files that failed to load
will be printed to stdout.

"Success" means that the import completed without raising an exception.
