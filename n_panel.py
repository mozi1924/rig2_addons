import bpy
from .ui import Rig2UIDrawer
from .preferences import get_preferences

class RIG2_PT_SidePanel_Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rig/2'

    @classmethod
    def poll(cls, context):
        # 首先检查插件设置中是否启用了 N 面板
        prefs = get_preferences()
        if not prefs.show_n_panel:
            return False
            
        # 接着执行原有的骨架检测逻辑
        obj = context.active_object
        if obj and obj.type == 'ARMATURE':
            if obj.pose and "logic" in obj.pose.bones:
                bone = obj.pose.bones["logic"]
                return bone.get("is_rig2") == 1
        return False

class RIG2_PT_SidePanel_Main(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Rig/2 Control Center"
    bl_idname = "RIG2_PT_side_panel_main"

    def draw(self, context):
        self.layout.operator("rig2.reset_props", text="Reset All Defaults", icon='LOOP_BACK')

class RIG2_PT_SidePanel_Limbs(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Limbs & IK-FK Switch"
    bl_idname = "RIG2_PT_side_panel_limbs"
    bl_parent_id = "RIG2_PT_side_panel_main"

    def draw(self, context):
        Rig2UIDrawer.draw_limbs(self.layout, context)

class RIG2_PT_SidePanel_Head(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Face & Head Details"
    bl_idname = "RIG2_PT_side_panel_head"
    bl_parent_id = "RIG2_PT_side_panel_main"

    def draw(self, context):
        Rig2UIDrawer.draw_head(self.layout, context)

class RIG2_PT_SidePanel_Advanced(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Performance & Settings"
    bl_idname = "RIG2_PT_side_panel_advanced"
    bl_parent_id = "RIG2_PT_side_panel_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        pass

class RIG2_PT_SidePanel_Misc(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Character Style"
    bl_idname = "RIG2_PT_side_panel_misc"
    bl_parent_id = "RIG2_PT_side_panel_advanced"

    def draw(self, context):
        Rig2UIDrawer.draw_misc(self.layout, context)

class RIG2_PT_SidePanel_Perf(RIG2_PT_SidePanel_Base, bpy.types.Panel):
    bl_label = "Optimization"
    bl_idname = "RIG2_PT_side_panel_perf"
    bl_parent_id = "RIG2_PT_side_panel_advanced"

    def draw(self, context):
        Rig2UIDrawer.draw_perf(self.layout, context)

classes = (
    RIG2_PT_SidePanel_Main,
    RIG2_PT_SidePanel_Limbs,
    RIG2_PT_SidePanel_Head,
    RIG2_PT_SidePanel_Advanced,
    RIG2_PT_SidePanel_Misc,
    RIG2_PT_SidePanel_Perf,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
