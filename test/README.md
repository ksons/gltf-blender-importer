## Testing

The [glTF Sample Models](https://github.com/KhronosGroup/glTF-Sample-Models) are
used for automated testing of the importer. A model file is considered to pass
if importing it doesn't raise an exception.


### Instructions

To run tests. This will fetch the sample models on its first run (be warned,
this is a big download). The optional `--exe` argument is to allow you to test
multiple Blender versions.

    ./test.py run [--exe BLENDER-EXE-PATH]

To display the results of the last test run. These are stored in `report.json`
in this directory

    ./test.py report

To display the import times from the last test run

    ./test.py report-times

You can use the exit code from `run` and `report` (success=0) to determine if
the tests passed programatically.
