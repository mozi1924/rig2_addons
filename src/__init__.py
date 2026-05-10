from . import preferences, i18n, licensing
from .modules import rig_controls, binding
from .modules import face_cap, r2bb
from .modules.rig_controls import miframes

modules = [
    i18n,
    licensing,
    preferences,
    rig_controls,
    face_cap,
    r2bb,
    miframes,
    binding,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()
