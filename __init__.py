bl_info = {
    "name": "Rig2",
    "author": "mozi1924",
    "version": (1, 1, 9),
    "blender": (4, 5, 0),
    "location": "Properties > Data, 3D View > Side Panel",
    "description": "A modular binding tool for Rig2 Armatures with Face/MoCap support ready",
    "category": "Rigging",
}

import bpy
from .src import register as src_register
from .src import unregister as src_unregister

def register():
    src_register()

def unregister():
    src_unregister()

if __name__ == "__main__":
    register()
