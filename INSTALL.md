See also the [Blender manual on installing
add-ons](https://docs.blender.org/manual/en/latest/preferences/addons.html).

## Installing from a Release ZIP

Download the latest release from the
[Releases](https://github.com/ksons/gltf-blender-importer/releases) page. It
should be a ZIP file with a name like `io_scene_gltf_ksons-X.Y.Z.zip`.

Open Blender and select **File > User Preferences** (or **Edit > user
Preferences** if that doesn't exist). Change to the **Add-ons** tab and select
**Install Add-on from File...** at the bottom of the screen (or **Install...**
at the top of the screen if that doesn't exist). Pick the ZIP file you
downloaded. The add-on is now installed.

You still need to enable it. In the **Add-ons** tab, put 'gltf' in the search
box and tick the checkbox next to **Import-Export: KSons' glTF 2.0 Importer**.

<img src="./doc/addon-install.png"/>


## Installing from Source

Obtain the source code, eg.

    git clone https://github.com/ksons/gltf-blender-importer.git

You can create a ZIP to install with the method above by running the script
`make_package.py`. A ZIP file `io_scene_gltf_ksons.zip` will be created in the
`dist/` folder.

Otherwise, find your Blender add-on directory. It is most commonly:

* **On Windows**, `C:\Users\<YOUR USER NAME>\AppData\Roaming\Blender
  Foundation\Blender\<YOUR BLENDER VERSION>\scripts\addons\`
* **On Linux**, `/home/<YOUR USER NAME>/.config/blender/<YOUR BLENDER
  VERSION>/scripts/addons/`
* **On OSX**, `/Users/<YOUR USER NAME>/Library/Application
  Support/Blender/<YOUR BLENDER VERSION>/scripts/addons/`

Alternatively, open Blender, switch to the Python console, and enter
`print(bpy.utils.user_resource('SCRIPTS', 'addons'))` to have it printed for
you.

Then copy (or, for easier development, symbolically link) the `io_scene_gltf`
folder from the `addons` folder in this repo to your Blender add-on directory.

Finally enable the add-on the same way as above.
