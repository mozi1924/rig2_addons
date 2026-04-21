import bpy

def register_classes(classes, module_name="Rig2"):
    """Register a collection of classes with error handling."""
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"{module_name} register error for {cls.__name__}: {exc}")

def unregister_classes(classes):
    """Unregister a collection of classes in reverse order."""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

def register_module(module):
    """Call register() on a module if it exists."""
    if hasattr(module, "register"):
        module.register()

def unregister_module(module):
    """Call unregister() on a module if it exists."""
    if hasattr(module, "unregister"):
        module.unregister()
