# gltf-blender-importer

[![Build Status](https://travis-ci.org/ksons/gltf-blender-importer.svg?branch=master)](https://travis-ci.org/ksons/gltf-blender-importer)

Blender importer for glTF 2.0.

## Installation
See [INSTALL.md](INSTALL.md) for further installation instructions.

For Blender 2.79, download the latest release here

<a href="https://github.com/ksons/gltf-blender-importer/releases/download/v0.4.0/io_scene_gltf-0.4.0.zip"><img src="./doc/archive.png"/></a>

You can install the archive using the **Install from File...** button in **File >
User Preferences... > Add-ons**. After installing you have to find the add-on
and enable it (tick the checkbox next to its name).
<p align="center"><img width="50%" src="./doc/addon-install.png"/></p>

The importer is then available from  **File > Import > glTF JSON (.gltf/.glb)**.

For Blender 2.80, clone this repo and checkout the
[`blender-2.8`](https://github.com/ksons/gltf-blender-importer/tree/blender-2.8)
branch. Install with the instructions in [INSTALL.md](INSTALL.md).

## Supported glTF Extensions
* EXT_property_animation (tentative until stabilized, material properties only)
* KHR_lights_punctual
* KHR_materials_pbrSpecularGlossiness
* KHR_materials_unlit
* KHR_texture_transform
* MSFT_texture_dds

## Samples Renderings
![BoomBox](https://github.com/ksons/gltf-blender-importer/blob/master/doc/boom-box.png)
![Corset](https://github.com/ksons/gltf-blender-importer/blob/master/doc/corset.png)
![Lantern](https://github.com/ksons/gltf-blender-importer/blob/master/doc/lantern.png)
