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
        rig_props = obj.rig2_props
        handled = set()
        
        if "prop.limbs" in pose_bones:
            bone = pose_bones["prop.limbs"]
            
            l_props = ["arm-L-fk-ik", "arm-L-wrist-ik", "leg-L-fk-ik"]
            r_props = ["arm-R-fk-ik", "arm-R-wrist-ik", "leg-R-fk-ik"]
            
            if rig_props.mirror_display:
                l_props, r_props = r_props, l_props

            row = layout.row()
            col = row.column(align=True)
            for p in l_props:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in r_props:
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
            for p in ["Tongue", "enable_neck", "eyebrow", "head_inherit_rotation", "layout_mode", "panel_to_face"]:
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
        rig_props = obj.rig2_props
        handled = set()
        if "prop.prop" in pose_bones:
            bone = pose_bones["prop.prop"]
            
            eye_props = ["enable_left_eye", "enable_right_eye"]
            if rig_props.mirror_display:
                eye_props = ["enable_right_eye", "enable_left_eye"]
                
            grid = layout.grid_flow(columns=2, align=True)
            for p in eye_props:
                if Rig2UIDrawer.draw_prop(grid, bone, p): handled.add(p)
            
            # Mouth is no longer mirrored and is a single property
            if Rig2UIDrawer.draw_prop(layout, bone, "enable_mouth"): handled.add("enable_mouth")

            col = layout.column(align=True)
            for p in ["view_body_boolen", "render_body_boolen", "view_face_boolen", "render_face_boolen", "view-subdivision", "render-subdivision"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_logic_props(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        if "logic" in pose_bones:
            bone = pose_bones["logic"]
            internal_keys = {'_RNA_UI', 'is_rig2'}
            logic_props = [k for k in bone.keys() if k not in internal_keys]
            if logic_props:
                col = layout.column(align=True)
                for k in sorted(logic_props):
                    # Detect if it's likely a boolean (type check + min/max check)
                    is_bool = False
                    try:
                        ui_data = bone.id_properties_ui(k).as_dict()
                        if ui_data.get('min') == 0 and ui_data.get('max') == 1 and isinstance(bone[k], (int, bool)):
                            is_bool = True
                    except:
                        if isinstance(bone[k], bool):
                            is_bool = True
                    
                    if is_bool:
                        col.prop(bone, f'["{k}"]', text=k, toggle=True)
                    else:
                        col.prop(bone, f'["{k}"]', text=k, slider=True)
            else:
                layout.label(text="No logic properties found.")

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
    def draw(self, context):
        obj = get_context_object(context)
        if obj:
            layout = self.layout
            layout.prop(obj.rig2_props, "mirror_display", text="Mirror L/R", icon='MOD_MIRROR', toggle=True)

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

class RIG2_PT_UtilityPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Utilities"
    bl_idname = "RIG2_PT_utility_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        obj = get_context_object(context)
        if not obj: return
        layout = self.layout
        
        # Mine-Imator Hub Box
        box = layout.box()
        row = box.row()
        row.label(text="miframes(Mine-Imator) Tools", icon='IMPORT')

        # MI Mapping Mode (Inside Box, Auto-detecting style)
        if "logic" in obj.pose.bones:
            bone = obj.pose.bones["logic"]
            if "mi_mapping_mode" in bone:
                col = box.column(align=True)
                # Auto-detect boolean toggle vs slider logic (Synced with draw_logic_props logic)
                is_bool = False
                try:
                    ui_data = bone.id_properties_ui("mi_mapping_mode").as_dict()
                    # Logic: if min/max is 0-1 and it's an int/bool, use toggle
                    if ui_data.get('min') == 0 and ui_data.get('max') == 1 and isinstance(bone["mi_mapping_mode"], (int, bool)):
                        is_bool = True
                except:
                    pass
                
                display_name = FRIENDLY_NAMES.get("mi_mapping_mode", "MI Mapping Mode")
                if is_bool:
                    col.prop(bone, '["mi_mapping_mode"]', text=display_name, toggle=True)
                else:
                    col.prop(bone, '["mi_mapping_mode"]', text=display_name, slider=True)
                box.separator()

        # Action Importer
        col = box.column(align=True)
        col.prop(obj.rig2_props, "mi_selected_model", text="Template")
        
        row = col.row(align=True)
        row.prop(obj.rig2_props, "mi_start_frame", text="Start At")
        row.prop(obj.rig2_props, "mi_adjust_end_frame", text="Auto End", toggle=True)
        
        col.operator("mi.import_action", text="Load .miframes", icon='ANIM_DATA')

class RIG2_PT_LogicPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "logic"
    bl_idname = "RIG2_PT_logic_panel"
    bl_parent_id = "RIG2_PT_danger_panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        prefs = get_preferences()
        if not (prefs and prefs.show_logic_props):
            return False
        return super().poll(context)

    def draw(self, context):
        Rig2UIDrawer.draw_logic_props(self.layout, context)

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
        obj = get_context_object(context)
        if obj:
            layout = self.layout
            layout.prop(obj.rig2_props, "mirror_display", text="Mirror L/R", icon='MOD_MIRROR', toggle=True)

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
    RIG2_PT_UtilityPanel,
    RIG2_PT_DangerPanel,
    RIG2_PT_LogicPanel,
    RIG2_PT_SideMain,
    RIG2_PT_SideLimbs,
    RIG2_PT_SideHead,
)

def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"Rig2 Error registering {cls}: {e}")

def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            pass
