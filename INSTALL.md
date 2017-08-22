## For Users
These are the installation instructions for Blender 2.78, but they should
work with earlier versions too. This is basically how you install any Blender
addon.

1. First, get a copy of this repo. You can get one by downloading and
   unzipping the [ZIP](https://github.com/ksons/gltf-blender-importer/archive/master.zip),
   or by cloning the Git repo.

2. Second, find out where your Blender addon folder is. The typical
   location on each common OS is listed below:

   * **Windows**, `C:\Users\<YOUR USER NAME>\AppData\Roaming\Blender Foundation\Blender\<YOUR BLENDER VERSION>\scripts\addons\`
   * **Linux**, `/home/<YOUR USER NAME>/.config/blender/<YOUR BLENDER VERSION>/scripts/addons/`
   * **macOS**, `/Users/<YOUR USER NAME>/Library/Application Support/Blender/<YOUR BLENDER VERSION>/scripts/addons/`

   Alternatively, open Blender, switch to the Python console, and enter

   ```
   print(bpy.utils.user_resource('SCRIPTS','addons'))
   ```

   and it should print the addon folder's location.

3. Copy the `io_scene_gltf` folder from the copy of this repo that you got
   in step 1 into the addon folder you found in step 2. The addon is now
   "installed". You can delete your copy of the repo from step 1 now if
   you like.

4. Open Blender. Select **File > User Preferences** and switch to the
   **Add-ons** tab. In the search bar, type "gltf". An addon called
   "Import-Export: glTF 2.0 Importer" should appear (if it doesn't, hit
   **Refresh** and make sure you did the previous steps correctly). Check
   the tickbox next to the name. The addon is now "enabled".

   Click **Save User Settings** so Blender will remember that you've enabled
   it the next time it loads.

5. You're done! You can import glTF files through the **File > Import > glTF
   JSON** option.

To update, you'll need to repeat steps 1 and 3 (and restart Blender).


## For Developers
This is the recommended method if you want to develop the addon (it also
makes upgrading slightly easier).

In step 1, get the repo through git

    $ git clone https://github.com/ksons/gltf-blender-importer.git

In step 3, instead of _copying_ the `io_scene_gltf` folder into the addon
folder, symbolically link it. On Linux, this is done with

    $ cd <YOUR ADDON FOLDER FROM STEP 2>
    $ ln -s <PATH TO THE io_scene_gltf FOLDER>

You can now edit the addon files, check out a different branch, etc. and you
just have to restart Blender for it to be using the new version of the
addon in your repo.

To upgrade, just pull the latest version (and restart Blender).
