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

            layout.label(text="Arms", icon='CON_ARMATURE')
            row = layout.row()
            col = row.column(align=True)
            for p in l_props[:2]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in r_props[:2]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
                
            layout.separator()
            layout.label(text="Legs", icon='CON_ARMATURE')
            row = layout.row()
            col = row.column(align=True)
            for p in l_props[2:]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in r_props[2:]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
                
            layout.separator()
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
            row = layout.row()
            col = row.column(align=True)
            for p in ["jaw", "eyebrow_width"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in ["mouth_shape", "eye_tracker"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
                
            layout.separator()
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["Tongue", "enable_neck", "eyebrow"]:
                if Rig2UIDrawer.draw_prop(grid, bone, p, toggle=True): handled.add(p)
            layout.prop(rig_props, "lash_enum", icon='STRANDS')
            handled.add("lash")
            
            layout.separator()
            col = layout.column(align=True)
            for p in ["brow_auto_rotation", "neck_length", "head_inherit_rotation"]:
                if Rig2UIDrawer.draw_prop(col, bone, p, toggle=(p=="head_inherit_rotation")): handled.add(p)
                
            layout.separator()
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["layout_mode", "panel_to_face"]:
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

            layout.separator()
            layout.label(text="Body", icon='USER')
            row = layout.row(align=True)
            for p in ["view_body_boolen", "render_body_boolen"]:
                if Rig2UIDrawer.draw_prop(row, bone, p): handled.add(p)
                
            layout.label(text="Face", icon='MONKEY')
            row = layout.row(align=True)
            for p in ["view_face_boolen", "render_face_boolen"]:
                if Rig2UIDrawer.draw_prop(row, bone, p): handled.add(p)
                
            layout.label(text="Subdivision", icon='MOD_SUBSURF')
            row = layout.row(align=True)
            for p in ["view-subdivision", "render-subdivision"]:
                if Rig2UIDrawer.draw_prop(row, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_logic_props(layout, context):
        obj = get_context_object(context)
        if not obj: return
        pose_bones = obj.pose.bones
        if "logic" in pose_bones:
            bone = pose_bones["logic"]
            internal_keys = {'_RNA_UI', 'is_rig2', 'mi_mapping_mode'}
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
            layout.separator()
            layout.operator("rig2.keyframe_state", text="Keyframe Current State", icon='DECORATE_KEYFRAME')

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
    bl_label = "Performance & Optimization"
    bl_idname = "RIG2_PT_advanced_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass

class RIG2_PT_MiscPanel(RIG2_PT_PropBase, bpy.types.Panel):
    bl_label = "Character Style"
    bl_idname = "RIG2_PT_misc_panel"
    bl_parent_id = "RIG2_PT_main_panel"
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
    bl_label = "Mine-Imator Anim Tools"
    bl_idname = "RIG2_PT_utility_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        obj = get_context_object(context)
        if not obj: return
        layout = self.layout

        has_mi2bl = hasattr(bpy.ops, "mi") and hasattr(bpy.ops.mi, "import_object_action")

        # Settings Region
        layout.label(text="Settings", icon='PREFERENCES')
        box = layout.box()

        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(obj.rig2_props, "mi_start_frame", text="Start At")
        row.prop(obj.rig2_props, "mi_adjust_end_frame", text="Auto End", toggle=True)

        if "logic" in obj.pose.bones:
            bone = obj.pose.bones["logic"]
            if "mi_mapping_mode" in bone:
                box.separator()
                col = box.column(align=True)
                is_bool = False
                try:
                    ui_data = bone.id_properties_ui("mi_mapping_mode").as_dict()
                    if ui_data.get('min') == 0 and ui_data.get('max') == 1 and isinstance(bone["mi_mapping_mode"], (int, bool)):
                        is_bool = True
                except:
                    pass

                display_name = FRIENDLY_NAMES.get("mi_mapping_mode", "Mapping Mode")
                if is_bool:
                    col.prop(bone, '["mi_mapping_mode"]', text=display_name, toggle=True)
                else:
                    col.prop(bone, '["mi_mapping_mode"]', text=display_name, slider=True)

        layout.separator()

        # Action Region
        layout.label(text="Action", icon='ACTION_TWEAK')
        row = layout.row()
        row.enabled = has_mi2bl
        row.operator("mi.import_action", text="Load Anim (.mi*)", icon='IMPORT')
        if not has_mi2bl:
            layout.label(text="Requires mi2bl addon", icon='INFO')

        # Show Bake MI → FK button when MI mapping is active
        mi_active = False
        if "logic" in obj.pose.bones:
            mi_active = obj.pose.bones["logic"].get("mi_mapping_mode", 0) > 0

        if mi_active:
            layout.separator()
            layout.label(text="Convert", icon='ANIM_DATA')
            row = layout.row()
            row.scale_y = 1.4
            row.operator("mi.bake_to_fk", text="Bake MI → FK", icon='EXPORT')


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
