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


def register_modules(modules, module_name="Rig2"):
    """Call register() on modules in declaration order."""
    for module in modules:
        register_fn = getattr(module, "register", None)
        if not callable(register_fn):
            continue
        try:
            register_fn()
        except Exception as exc:
            module_ref = getattr(module, "__name__", repr(module))
            _log.warning("%s module register error for %s: %s", module_name, module_ref, exc)


def unregister_modules(modules, module_name="Rig2"):
    """Call unregister() on modules in reverse declaration order."""
    for module in reversed(tuple(modules)):
        unregister_fn = getattr(module, "unregister", None)
        if not callable(unregister_fn):
            continue
        try:
            unregister_fn()
        except Exception as exc:
            module_ref = getattr(module, "__name__", repr(module))
            _log.debug("%s module unregister error for %s: %s", module_name, module_ref, exc)


def register_module(module):
    """Call register() on a module if it exists."""
    if hasattr(module, "register"):
        module.register()
