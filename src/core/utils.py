import bpy

def get_context_object(context):
    """
    Robustly get the object that the properties panel should display.
    Supports pinned objects, data tabs, and various contexts.
    """
    if context.area and context.area.type == 'PROPERTIES':
        id_data = context.space_data.id_data
        if id_data:
            if isinstance(id_data, bpy.types.Object):
                return id_data
            if isinstance(id_data, bpy.types.Armature):
                if context.active_object and context.active_object.data == id_data:
                    return context.active_object
                for obj in bpy.data.objects:
                    if obj.data == id_data:
                        return obj
    
    return context.object or context.active_object

def is_rig2_armature(obj):
    """Check if the object is a Rig2 armature."""
    if obj and obj.type == 'ARMATURE':
        if obj.pose and "logic" in obj.pose.bones:
            return obj.pose.bones["logic"].get("is_rig2") == 1
    return False


def _iter_context_areas(context):
    window_manager = getattr(context, "window_manager", None) if context else None
    for window in getattr(window_manager, "windows", []):
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            yield area


def tag_context_redraw(context=None, area_types=None):
    """Tag common UI areas for redraw."""
    context = context or getattr(bpy, "context", None)
    allowed_types = set(area_types) if area_types else None
    for area in _iter_context_areas(context):
        if allowed_types is not None and area.type not in allowed_types:
            continue
        try:
            area.tag_redraw()
        except Exception:
            pass


def refresh_rig_driver_batch(objects, *, context=None, redraw=True):
    """
    Refresh rig driver evaluation after custom property writes.
    Uses object tags + view layer update so driver values update immediately.
    """
    context = context or getattr(bpy, "context", None)
    seen = set()
    for obj in objects or []:
        if obj is None:
            continue

        pointer_getter = getattr(obj, "as_pointer", None)
        obj_key = pointer_getter() if callable(pointer_getter) else id(obj)
        if obj_key in seen:
            continue
        seen.add(obj_key)

        try:
            obj.update_tag(refresh={"OBJECT", "DATA"})
        except Exception:
            pass

    view_layer = getattr(context, "view_layer", None) if context else None
    if view_layer is not None:
        try:
            view_layer.update()
        except Exception:
            pass

    if redraw:
        tag_context_redraw(context, area_types={"VIEW_3D", "PROPERTIES"})


def refresh_rig_drivers(obj=None, *, context=None, redraw=True):
    refresh_rig_driver_batch([obj] if obj is not None else [], context=context, redraw=redraw)
