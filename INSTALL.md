See also the [Blender manual on installing
add-ons](https://docs.blender.org/manual/en/latest/preferences/addons.html).

## Installing from a Release Archive

Download the latest release from the
[Releases](https://github.com/ksons/gltf-blender-importer/releases) page. It
should be a ZIP file with a name like `io_scene_gltf-X.Y.Z.zip`.

Open Blender and select **File > User Preferences**. Change to the **Add-ons**
tab and select **Install Add-on from File...** at the bottom of the screen. Pick
the ZIP file you downloaded. The add-on is now installed.

You still need to activate it. In the **Add-ons** tab, put "gltf" in the search
box and tick the checkbox next to **Import-Export: glTF 2.0 Importer**.

<img src="./doc/addon-install.png"/>


## Installing from Source

Obtain the source code, either by cloning the git repo or downloading a
[ZIP](https://github.com/ksons/gltf-blender-importer/archive/master.zip) from
Github. If you want to install from a branch, clone the git repo and check out
the branch.

### Easy way (requires Python)

Run the script `make_package.py` found in the top-level directory. A ZIP file
`io_scene_gltf.zip` will be created in the `dist/` folder. Install this ZIP file
the same way as described above.

### Harder way

Find your Blender add-on directory. It is most commonly:

* **On Windows**, `C:\Users\<YOUR USER NAME>\AppData\Roaming\Blender
  Foundation\Blender\<YOUR BLENDER VERSION>\scripts\addons\`
* **On Linux**, `/home/<YOUR USER NAME>/.config/blender/<YOUR BLENDER
  VERSION>/scripts/addons/`
* **On OSX**, `/Users/<YOUR USER NAME>/Library/Application
  Support/Blender/<YOUR BLENDER VERSION>/scripts/addons/`

Alternatively, open Blender, switch to the Python console, and enter `print(bpy.utils.user_resource('SCRIPTS', 'addons'))` to have it printed for you.

Then copy the `io_scene_gltf` folder from the `addons` folder in this repo to
your Blender add-on directory.

Then just activate the add-on in the same way as described above.

**Tip**: If you want to change or contribute to the add-on, I recommend you
symbolically link (`ln -s`) the `io_scene_gltf` folder into your Blender add-on
directory instead of copying it. You can then test changes by just restarting
Blender instead of having to re-install the add-on after each change.
