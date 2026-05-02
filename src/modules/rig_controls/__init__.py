from . import props, ops, ui
from ...core.registration import register_modules, unregister_modules

_MODULES = (
    props,
    ops,
    ui,
)

def register():
    register_modules(_MODULES, module_name="RigControls")

def unregister():
    unregister_modules(_MODULES, module_name="RigControls")
