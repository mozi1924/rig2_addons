import logging

import bpy

_log = logging.getLogger(__name__)


def register_classes(classes, module_name="Rig2"):
    """Register a collection of classes with error handling."""
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            _log.warning("%s register error for %s: %s", module_name, cls.__name__, exc)


def unregister_classes(classes):
    """Unregister a collection of classes in reverse order."""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            _log.debug("unregister error for %s: %s", cls.__name__, exc)

def register_module(module):
    """Call register() on a module if it exists."""
    if hasattr(module, "register"):
        module.register()

def unregister_module(module):
    """Call unregister() on a module if it exists."""
    if hasattr(module, "unregister"):
        module.unregister()
