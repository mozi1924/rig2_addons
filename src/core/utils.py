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
