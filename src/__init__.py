from . import preferences
from .modules import rig_controls, binding

# Future modules can be added here
# from .modules import face_cap, mo_cap

modules = [
    preferences,
    rig_controls,
    binding,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()
