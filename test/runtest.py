import unittest
import glob
import os
from subprocess import Popen, DEVNULL, run

base_dir = os.path.dirname(os.path.abspath(__file__))
samples_path = os.path.join(base_dir, 'glTF-Sample-Models', '2.0')
test_script = os.path.join(base_dir, 'import_file.py')

class SampleModelRunTests(unittest.TestCase):
    pass

def test_generator(filename):
    def test(self):
        scripts_dir = os.path.join(base_dir, os.pardir)
        env = os.environ.copy()
        env['BLENDER_USER_SCRIPTS'] = scripts_dir
        
        
        proc = run(
            [
                'blender',
                '--python-exit-code', '1',
                '--background', # run UI-less
                '--factory-startup', # factory settings
                '--addons', 'io_scene_gltf', # enable the addon
                '--python', test_script, # run the test script
                '-noaudio',
                '--',
                filename
    
            ],
            env=env,
            stdout=DEVNULL,
            check=False
        )
        self.assertEqual(proc.returncode, 0, "Blender quit")
        print(proc.returncode)

    return test

if __name__ == '__main__':
    files = (
        glob.glob(samples_path + '/**/*.gltf', recursive=True) +
        glob.glob(samples_path + '/**/*.glb', recursive=True)
    )
    print("%i sample files" % len(files))
    for filename in files:
        test = test_generator(filename)
        test.__name__ = "test_%s (%s)" % (os.path.basename(filename), os.path.relpath(filename, samples_path))
        setattr(SampleModelRunTests, test.__name__, test)
    unittest.main()