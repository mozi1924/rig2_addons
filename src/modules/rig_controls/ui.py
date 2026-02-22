import bpy
from .props import FRIENDLY_NAMES
from ...core.utils import get_context_object, is_rig2_armature
from ...preferences import get_preferences

class Rig2UIDrawer:
    """Shared drawing methods for Rig2 controls"""
    
    @staticmethod
    def draw_prop(layout, bone, prop_name, text="", slider=True, toggle=False):
        if prop_name in bone:
            display_text = text or FRIENDLY_NAMES.get(prop_name, prop_name)
            if toggle:
                layout.prop(bone, f'["{prop_name}"]', text=display_text, toggle=True)
            else:
                layout.prop(bone, f'["{prop_name}"]', text=display_text, slider=slider)
            return True
        return False

    @staticmethod
    def draw_remaining_props(layout, bone, handled_set):
        internal_keys = {'_RNA_UI', 'is_rig2'}
        remaining = [k for k in bone.keys() if k not in handled_set and k not in internal_keys]
        if remaining:
            sublog = layout.column(align=True)
            sublog.label(text="Additional Props:", icon='ADD')
            for k in remaining:
                sublog.prop(bone, f'["{k}"]', slider=True)

    @staticmethod
    def draw_limbs(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        handled = set()
        if "prop.limbs" in pose_bones:
            bone = pose_bones["prop.limbs"]
            row = layout.row()
            col = row.column(align=True)
            for p in ["arm-L-fk-ik", "arm-L-wrist-ik", "leg-L-fk-ik"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in ["arm-R-fk-ik", "arm-R-wrist-ik", "leg-R-fk-ik"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            row = layout.row(align=True)
            for p in ["arm-world-ik", "ik-stretch.arm", "ik-stretch.leg"]:
                if Rig2UIDrawer.draw_prop(row, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_head(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        if "prop.head" in pose_bones:
            bone = pose_bones["prop.head"]
            layout.prop(rig_props, "lash_enum", icon='STRANDS')
            handled.add("lash")
            row = layout.row()
            col = row.column(align=True)
            for p in ["jaw", "eyebrow_width", "mouth_shape"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in ["neck_length", "eye_tracker", "brow_auto_rotation"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["Tongue", "enable_neck", "eyebrow", "inherit_rotation", "layout_mode", "panel_to_face"]:
                if Rig2UIDrawer.draw_prop(grid, bone, p, toggle=True): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_misc(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        if "prop.misc" in pose_bones:
            bone = pose_bones["prop.misc"]
            row = layout.row()
            if Rig2UIDrawer.draw_prop(row, bone, "alex", toggle=True): handled.add("alex")
            if Rig2UIDrawer.draw_prop(row, bone, "hands", toggle=True): handled.add("hands")
            layout.prop(rig_props, "feet_enum", text="Ankle/Feet Style")
            handled.add("feet_style")
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_perf(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        handled = set()
        if "prop.prop" in pose_bones:
            bone = pose_bones["prop.prop"]
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["enable_left_eye", "enable_right_eye", "enable_left_mouth", "enable_right_mouth"]:
                if Rig2UIDrawer.draw_prop(grid, bone, p): handled.add(p)
            col = layout.column(align=True)
            for p in ["view_body_boolen", "render_body_boolen", "view_face_boolen", "render_face_boolen", "view-subdivision", "render-subdivision"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

# --- Properties Panel ---

class RIG2_PT_PropBase:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_order = -10
    
    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))

class RIG2_PT_MainPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Rig/2 Control Center"
    bl_idname = "RIG2_PT_main_panel"
    def draw(self, context): pass

class RIG2_PT_LimbsPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Limbs & IK-FK Switch"
    bl_idname = "RIG2_PT_limbs_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    def draw(self, context): Rig2UIDrawer.draw_limbs(self.layout, context)

class RIG2_PT_HeadPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Face & Head Details"
    bl_idname = "RIG2_PT_head_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    def draw(self, context): Rig2UIDrawer.draw_head(self.layout, context)

class RIG2_PT_AdvancedPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Performance & Settings"
    bl_idname = "RIG2_PT_advanced_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass

class RIG2_PT_MiscPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Character Style"
    bl_idname = "RIG2_PT_misc_panel"
    bl_parent_id = "RIG2_PT_advanced_panel"
    def draw(self, context): Rig2UIDrawer.draw_misc(self.layout, context)

class RIG2_PT_PerfPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Optimization"
    bl_idname = "RIG2_PT_perf_panel"
    bl_parent_id = "RIG2_PT_advanced_panel"
    def draw(self, context): Rig2UIDrawer.draw_perf(self.layout, context)

class RIG2_PT_DangerPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Danger Zone"
    bl_idname = "RIG2_PT_danger_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        layout.label(text="Caution: Resetting defaults!", icon='ERROR')
        col = layout.column()
        col.alert = True
        col.operator("rig2.reset_props", text="Reset All Defaults", icon='LOOP_BACK')

# --- Sidebar (N) Panel ---

class RIG2_PT_SideBase:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rig/2'

    @classmethod
    def poll(cls, context):
        prefs = get_preferences()
        if not prefs or not prefs.show_n_panel:
            return False
        return is_rig2_armature(context.active_object)

class RIG2_PT_SideMain(RIG2_PT_SideBase, bpy.types.Panel):
    bl_label = "Rig Control"
    bl_idname = "RIG2_PT_side_main"
    def draw(self, context): 
        self.layout.operator("rig2.reset_props", text="Reset All Defaults", icon='LOOP_BACK')

class RIG2_PT_SideLimbs(RIG2_PT_SideBase, bpy.types.Panel):
    bl_label = "Limbs"
    bl_idname = "RIG2_PT_side_limbs"
    bl_parent_id = "RIG2_PT_side_main"
    def draw(self, context): Rig2UIDrawer.draw_limbs(self.layout, context)

class RIG2_PT_SideHead(RIG2_PT_SideBase, bpy.types.Panel):
    bl_label = "Face"
    bl_idname = "RIG2_PT_side_head"
    bl_parent_id = "RIG2_PT_side_main"
    def draw(self, context): Rig2UIDrawer.draw_head(self.layout, context)


classes = (
    RIG2_PT_MainPanel,
    RIG2_PT_LimbsPanel,
    RIG2_PT_HeadPanel,
    RIG2_PT_AdvancedPanel,
    RIG2_PT_MiscPanel,
    RIG2_PT_PerfPanel,
    RIG2_PT_DangerPanel,
    RIG2_PT_SideMain,
    RIG2_PT_SideLimbs,
    RIG2_PT_SideHead,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
