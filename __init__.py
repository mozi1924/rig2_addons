bl_info = {
    "name": "Rig2 Binding Tool",
    "author": "Antigravity",
    "version": (1, 0),
    "blender": (3, 0, 0),
    "location": "Properties > Data, 3D View > Side Panel",
    "description": "A customized binding tool for Rig2 Armatures with dynamic UI mapping",
    "category": "Rigging",
}

import bpy
from . import properties, ui, controller, preferences, n_panel, ops

modules = (
    properties,
    preferences,
    controller,
    ui,
    n_panel,
    ops,
)

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()

if __name__ == "__main__":
    register()
