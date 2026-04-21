import bpy

from ...core.constants import INTERNAL_KEYS
from ...core.registration import register_classes, unregister_classes
from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import iface as _
from ...preferences import get_preferences
from ...ui.base import RIG2_PT_PanelBase, RIG2_PT_SidePanelBase


class Rig2UIDrawer:
    """Shared drawing methods for Rig2 controls."""

    @staticmethod
    def _display_name(prop_name, text=""):
        from .props import FRIENDLY_NAMES
        return _(text or FRIENDLY_NAMES.get(prop_name, prop_name))

    @staticmethod
    def _is_bool_prop(bone, prop_name):
        try:
            ui_data = bone.id_properties_ui(prop_name).as_dict()
            if ui_data.get("min") == 0 and ui_data.get("max") == 1 and isinstance(bone[prop_name], (int, bool)):
                return True
        except Exception:
            pass
        return isinstance(bone.get(prop_name), bool)

    @staticmethod
    def draw_prop(layout, bone, prop_name, text="", slider=True, toggle=False):
        if prop_name not in bone:
            return False

        layout.prop(
            bone,
            f'["{prop_name}"]',
            text=Rig2UIDrawer._display_name(prop_name, text),
            slider=slider and not toggle,
            toggle=toggle,
        )
        return True

    @staticmethod
    def draw_auto_prop(layout, bone, prop_name, text=""):
        if prop_name not in bone:
            return False

        if Rig2UIDrawer._is_bool_prop(bone, prop_name):
            layout.prop(
                bone,
                f'["{prop_name}"]',
                text=Rig2UIDrawer._display_name(prop_name, text),
                toggle=True,
            )
        else:
            layout.prop(
                bone,
                f'["{prop_name}"]',
                text=Rig2UIDrawer._display_name(prop_name, text),
                slider=True,
            )
        return True

    @staticmethod
    def draw_prop_group(layout, bone, prop_names, handled_set, *, toggle=False):
        for prop_name in prop_names:
            if Rig2UIDrawer.draw_prop(layout, bone, prop_name, toggle=toggle):
                handled_set.add(prop_name)

    @staticmethod
    def draw_split_props(layout, bone, left_props, right_props, handled_set):
        row = layout.row()
        left_col = row.column(align=True)
        right_col = row.column(align=True)
        Rig2UIDrawer.draw_prop_group(left_col, bone, left_props, handled_set)
        Rig2UIDrawer.draw_prop_group(right_col, bone, right_props, handled_set)

    @staticmethod
    def draw_remaining_props(layout, bone, handled_set):
        remaining = [
            key
            for key in bone.keys()
            if key not in handled_set and key not in INTERNAL_KEYS
        ]
        if not remaining:
            return

        column = layout.column(align=True)
        column.label(text=_("Additional Props:"), icon="ADD")
        for prop_name in sorted(remaining):
            Rig2UIDrawer.draw_auto_prop(column, bone, prop_name)

    @staticmethod
    def draw_main_toolbar(layout, obj, *, include_keyframe):
        layout.prop(
            obj.rig2_props,
            "mirror_display",
            text=_("Mirror L/R"),
            icon="MOD_MIRROR",
            toggle=True,
        )
        if include_keyframe:
            layout.separator()
            layout.operator(
                "rig2.keyframe_state",
                text=_("Keyframe Current State"),
                icon="DECORATE_KEYFRAME",
            )

    @staticmethod
    def draw_limbs(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        bone = pose_bones.get("prop.limbs")
        if not bone:
            return

        left_props = ["arm-L-fk-ik", "arm-L-wrist-ik", "leg-L-fk-ik"]
        right_props = ["arm-R-fk-ik", "arm-R-wrist-ik", "leg-R-fk-ik"]
        if rig_props.mirror_display:
            left_props, right_props = right_props, left_props

        layout.label(text=_("Arms"), icon="CON_ARMATURE")
        Rig2UIDrawer.draw_split_props(layout, bone, left_props[:2], right_props[:2], handled)

        layout.separator()
        layout.label(text=_("Legs"), icon="CON_ARMATURE")
        Rig2UIDrawer.draw_split_props(layout, bone, left_props[2:], right_props[2:], handled)

        layout.separator()
        row = layout.row(align=True)
        Rig2UIDrawer.draw_prop_group(
            row,
            bone,
            ["arm-world-ik", "ik-stretch.arm", "ik-stretch.leg"],
            handled,
        )
        Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_head(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        bone = pose_bones.get("prop.head")
        if not bone:
            return

        row = layout.row()
        left_col = row.column(align=True)
        right_col = row.column(align=True)
        Rig2UIDrawer.draw_prop_group(left_col, bone, ["jaw", "eyebrow_width"], handled)
        Rig2UIDrawer.draw_prop_group(right_col, bone, ["mouth_shape", "eye_tracker"], handled)

        layout.separator()
        grid = layout.grid_flow(columns=2, align=True)
        Rig2UIDrawer.draw_prop_group(grid, bone, ["Tongue", "enable_neck", "eyebrow"], handled, toggle=True)
        layout.prop(rig_props, "lash_enum", icon="STRANDS")
        handled.add("lash")

        layout.separator()
        column = layout.column(align=True)
        Rig2UIDrawer.draw_prop_group(
            column,
            bone,
            ["brow_auto_rotation", "neck_length"],
            handled,
            toggle=False,
        )
        if "head_inherit_rotation" in bone:
            Rig2UIDrawer.draw_prop(column, bone, "head_inherit_rotation", toggle=True)
            handled.add("head_inherit_rotation")

        layout.separator()
        grid = layout.grid_flow(columns=2, align=True)
        Rig2UIDrawer.draw_prop_group(grid, bone, ["layout_mode", "panel_to_face"], handled, toggle=True)

        Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_misc(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        bone = pose_bones.get("prop.misc")
        if not bone:
            return

        row = layout.row()
        if Rig2UIDrawer.draw_prop(row, bone, "alex", toggle=True):
            handled.add("alex")
        if Rig2UIDrawer.draw_prop(row, bone, "hands", toggle=True):
            handled.add("hands")

        layout.prop(rig_props, "feet_enum", text=_("Ankle/Feet Style"))
        handled.add("feet_style")
        Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_perf(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        bone = pose_bones.get("prop.prop")
        if not bone:
            return

        eye_props = ["enable_left_eye", "enable_right_eye"]
        if rig_props.mirror_display:
            eye_props.reverse()

        grid = layout.grid_flow(columns=2, align=True)
        Rig2UIDrawer.draw_prop_group(grid, bone, eye_props, handled)

        if Rig2UIDrawer.draw_prop(layout, bone, "enable_mouth"):
            handled.add("enable_mouth")

        layout.separator()
        layout.label(text=_("Body"), icon="USER")
        row = layout.row(align=True)
        Rig2UIDrawer.draw_prop_group(row, bone, ["view_body_boolen", "render_body_boolen"], handled)

        layout.label(text=_("Face"), icon="MONKEY")
        row = layout.row(align=True)
        Rig2UIDrawer.draw_prop_group(row, bone, ["view_face_boolen", "render_face_boolen"], handled)

        layout.label(text=_("Subdivision"), icon="MOD_SUBSURF")
        row = layout.row(align=True)
        Rig2UIDrawer.draw_prop_group(row, bone, ["view-subdivision", "render-subdivision"], handled)

        Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_logic_props(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        bone = pose_bones.get("logic")
        if not bone:
            return

        logic_props = [
            key
            for key in bone.keys()
            if key not in Rig2UIDrawer.INTERNAL_KEYS and key != "mi_mapping_mode"
        ]
        if not logic_props:
            layout.label(text=_("No logic properties found."))
            return

        column = layout.column(align=True)
        for prop_name in sorted(logic_props):
            Rig2UIDrawer.draw_auto_prop(column, bone, prop_name)


# Base classes moved to src.ui.base


class RIG2_PT_MainPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Rig/2 Control Center"
    bl_idname = "RIG2_PT_main_panel"

    def draw(self, context):
        obj = get_context_object(context)
        if obj:
            Rig2UIDrawer.draw_main_toolbar(self.layout, obj, include_keyframe=True)


class RIG2_PT_LimbsPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Limbs & IK-FK Switch"
    bl_idname = "RIG2_PT_limbs_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 10

    def draw(self, context):
        Rig2UIDrawer.draw_limbs(self.layout, context)


class RIG2_PT_HeadPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Face & Head Details"
    bl_idname = "RIG2_PT_head_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 20

    def draw(self, context):
        Rig2UIDrawer.draw_head(self.layout, context)


class RIG2_PT_AdvancedPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Performance & Optimization"
    bl_idname = "RIG2_PT_advanced_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 40

    def draw(self, context):
        Rig2UIDrawer.draw_perf(self.layout, context)


class RIG2_PT_MiscPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Character Style"
    bl_idname = "RIG2_PT_misc_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 30

    def draw(self, context):
        Rig2UIDrawer.draw_misc(self.layout, context)


class RIG2_PT_DangerPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Danger Zone"
    bl_idname = "RIG2_PT_danger_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 100
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=_("Caution: Resetting defaults!"), icon="ERROR")
        column = layout.column()
        column.alert = True
        column.operator("rig2.reset_props", text=_("Reset All Defaults"), icon="LOOP_BACK")


class RIG2_PT_UtilityPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Mine-Imator Anim Tools"
    bl_idname = "RIG2_PT_utility_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 50
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = get_context_object(context)
        if not obj:
            return

        layout = self.layout
        has_mi2bl = hasattr(bpy.ops, "mi") and hasattr(bpy.ops.mi, "import_object_action")

        settings_box = layout.box()
        settings_box.label(text=_("Settings"), icon="PREFERENCES")
        row = settings_box.row(align=True)
        row.prop(obj.rig2_props, "mi_start_frame", text=_("Start At"))
        row.prop(obj.rig2_props, "mi_adjust_end_frame", text=_("Auto End"), toggle=True)

        logic_bone = obj.pose.bones.get("logic")
        if logic_bone and "mi_mapping_mode" in logic_bone:
            Rig2UIDrawer.draw_auto_prop(settings_box, logic_bone, "mi_mapping_mode")

        action_box = layout.box()
        action_box.label(text=_("Action"), icon="ACTION_TWEAK")
        row = action_box.row()
        row.enabled = has_mi2bl
        row.operator("mi.import_action", text=_("Load Anim (.mi*)"), icon="IMPORT")
        if not has_mi2bl:
            action_box.label(text=_("Requires mi2bl addon"), icon="INFO")

        mi_active = bool(logic_bone and logic_bone.get("mi_mapping_mode", 0) > 0)
        if mi_active:
            convert_box = layout.box()
            convert_box.label(text=_("Convert"), icon="ANIM_DATA")
            row = convert_box.row()
            row.scale_y = 1.4
            row.operator("mi.bake_to_fk", text=_("Bake MI → FK"), icon="EXPORT")


class RIG2_PT_MIIKPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    """MI IK switches, for manual MI IK versus FK control."""

    bl_label = "MI IK Control"
    bl_idname = "RIG2_PT_mi_ik_panel"
    bl_parent_id = "RIG2_PT_utility_panel"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False

        obj = get_context_object(context)
        if not obj or "logic" not in obj.pose.bones:
            return False

        logic_bone = obj.pose.bones["logic"]
        ik_props = ("mi_ik_arm.L", "mi_ik_arm.R", "mi_ik_leg.L", "mi_ik_leg.R")
        return any(prop_name in logic_bone for prop_name in ik_props)

    def draw(self, context):
        obj = get_context_object(context)
        if not obj:
            return

        layout = self.layout
        rig_props = obj.rig2_props
        logic_bone = obj.pose.bones.get("logic")
        if not logic_bone:
            return

        arm_left = ["mi_ik_arm.L"]
        arm_right = ["mi_ik_arm.R"]
        leg_left = ["mi_ik_leg.L"]
        leg_right = ["mi_ik_leg.R"]
        if rig_props.mirror_display:
            arm_left, arm_right = arm_right, arm_left
            leg_left, leg_right = leg_right, leg_left

        handled = set()
        layout.label(text=_("Arm IK"), icon="CON_KINEMATIC")
        Rig2UIDrawer.draw_split_props(layout, logic_bone, arm_left, arm_right, handled)

        layout.separator()
        layout.label(text=_("Leg IK"), icon="CON_KINEMATIC")
        Rig2UIDrawer.draw_split_props(layout, logic_bone, leg_left, leg_right, handled)


class RIG2_PT_LogicPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "logic"
    bl_idname = "RIG2_PT_logic_panel"
    bl_parent_id = "RIG2_PT_danger_panel"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        prefs = get_preferences()
        if not (prefs and prefs.show_logic_props):
            return False
        return super().poll(context)

    def draw(self, context):
        Rig2UIDrawer.draw_logic_props(self.layout, context)


# SideBase moved to src.ui.base


class RIG2_PT_SideMain(RIG2_PT_SidePanelBase, bpy.types.Panel):
    bl_label = "Rig Control"
    bl_idname = "RIG2_PT_side_main"

    def draw(self, context):
        obj = get_context_object(context)
        if obj:
            Rig2UIDrawer.draw_main_toolbar(self.layout, obj, include_keyframe=False)


class RIG2_PT_SideLimbs(RIG2_PT_SidePanelBase, bpy.types.Panel):
    bl_label = "Limbs"
    bl_idname = "RIG2_PT_side_limbs"
    bl_parent_id = "RIG2_PT_side_main"

    def draw(self, context):
        Rig2UIDrawer.draw_limbs(self.layout, context)


class RIG2_PT_SideHead(RIG2_PT_SidePanelBase, bpy.types.Panel):
    bl_label = "Face"
    bl_idname = "RIG2_PT_side_head"
    bl_parent_id = "RIG2_PT_side_main"

    def draw(self, context):
        Rig2UIDrawer.draw_head(self.layout, context)


classes = (
    RIG2_PT_MainPanel,
    RIG2_PT_LimbsPanel,
    RIG2_PT_HeadPanel,
    RIG2_PT_AdvancedPanel,
    RIG2_PT_MiscPanel,
    RIG2_PT_UtilityPanel,
    RIG2_PT_MIIKPanel,
    RIG2_PT_DangerPanel,
    RIG2_PT_LogicPanel,
    RIG2_PT_SideMain,
    RIG2_PT_SideLimbs,
    RIG2_PT_SideHead,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
