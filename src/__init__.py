from . import preferences, i18n, licensing
from .modules import rig_controls, binding, face_cap

modules = [
    i18n,
    licensing,
    preferences,
    rig_controls,
    face_cap,
    binding,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()
