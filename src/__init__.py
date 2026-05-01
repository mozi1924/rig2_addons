from . import feature_registration, preferences, i18n, licensing
from .modules import rig_controls, binding

modules = [
    i18n,
    licensing,
    preferences,
    rig_controls,
    binding,
    feature_registration,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()
