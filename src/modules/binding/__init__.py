from . import ops
from ...core.registration import register_modules, unregister_modules

_MODULES = (ops,)

def register():
    register_modules(_MODULES, module_name="Binding")

def unregister():
    unregister_modules(_MODULES, module_name="Binding")
