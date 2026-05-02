from . import props, ops, ui, runtime
from ...core.registration import register_modules, unregister_modules

_MODULES = (
    props,
    ops,
    ui,
    runtime,
)


def register():
    register_modules(_MODULES, module_name="FaceCap")


def unregister():
    unregister_modules(_MODULES, module_name="FaceCap")
