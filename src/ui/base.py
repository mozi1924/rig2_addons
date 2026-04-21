import bpy
from ..core.utils import get_context_object, is_rig2_armature
from ..preferences import get_preferences


class RIG2_PT_PanelBase:
    """Base class for all Rig2 properties panels."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_order = -10

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))


class RIG2_PT_SidePanelBase:
    """Base class for all Rig2 3D View side panels (N-panel)."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rig/2'

    @classmethod
    def poll(cls, context):
        prefs = get_preferences()
        if not prefs or not prefs.show_n_panel:
            return False
        return is_rig2_armature(context.active_object)
