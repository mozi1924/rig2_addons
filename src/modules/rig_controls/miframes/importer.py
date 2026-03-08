import bpy
import json
import math
import sys
import os
import importlib
import re
from mathutils import Euler, Vector

# Rig2 depends on mi2bl for the core MI parsing and easing logic.
# This fulfills the "Rig2 needs mi2bl" requirement and merges duplicate code.
try:
    # In Blender, we can try to reach the mi2bl package
    from mi2bl.src import core
    MIBaseImporter = core.MIBaseImporter
    apply_mi_transition = core.apply_mi_transition
except (ImportError, ModuleNotFoundError):
    # Fallback if mi2bl is not found in path (Blender dev or missing addon)
    try:
        # Try local fallback if developing in the same workspace
        # (This is just for survival during refactoring)
        sys.path.append(os.path.join(os.path.dirname(__file__), "../../../../../mi2bl"))
        from src import core
        MIBaseImporter = core.MIBaseImporter
        apply_mi_transition = core.apply_mi_transition
    except:
        class MIBaseImporter:
            def check_file(self, *args, **kwargs):
                return None, "mi2bl addon is REQUIRED for MI imports. Please install mi2bl first."
            def setup_scene(self, *args, **kwargs): return 24, 24, 1.0
            def apply_interpolation(self, *args, **kwargs): pass
        def apply_mi_transition(*args, **kwargs): pass

try:
    from . import configs
except (ImportError, ValueError):
    import configs

class MI_OT_ImportAction(bpy.types.Operator, MIBaseImporter):
    """Import .miframes using a selected model configuration (REQUIRES Rig2)"""
    bl_idname = "mi.import_action"
    bl_label = "Load .miframes"
    bl_options = {'REGISTER', 'UNDO'}
    
    confirmed: bpy.props.BoolProperty(default=False)
    
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.miframes;*.miobject",
        options={'HIDDEN'},
        maxlen=255
    )

    def execute(self, context):
        arm = context.active_object
        if not arm or arm.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select the Rig2 Armature")
            return {'CANCELLED'}

        if not hasattr(arm, "rig2_props"):
            self.report({'ERROR'}, "Rig2 properties missing.")
            return {'CANCELLED'}

        data, err = self.check_file(self.filepath)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        is_model = data.get("is_model", True)
        if not is_model:
            # Re-direct to generic object importer in mi2bl if possible
            if hasattr(bpy.ops.mi, "import_object_action"):
                return bpy.ops.mi.import_object_action('INVOKE_DEFAULT', filepath=self.filepath)
            self.report({'ERROR'}, "This file is not a character model. Use the mi2bl object importer.")
            return {'CANCELLED'}

        # Get selected model from rig2_props
        if not hasattr(arm.rig2_props, "mi_selected_model"):
            self.report({'ERROR'}, "Rig2 model selection property missing.")
            return {'CANCELLED'}
            
        model_key = arm.rig2_props.mi_selected_model
        config = configs.MODELS.get(model_key)
        if not config:
            self.report({'ERROR'}, f"Model config '{model_key}' not found.")
            return {'CANCELLED'}

        tempo, fps_current, fps_scale = self.setup_scene(
            context, data, 
            arm.rig2_props.mi_start_frame, 
            arm.rig2_props.mi_adjust_end_frame
        )
        start_frame = arm.rig2_props.mi_start_frame

        kf_trans_map = {}
        def _add_trans(b_name, _time, _t_info):
            if b_name not in kf_trans_map:
                kf_trans_map[b_name] = []
            kf_trans_map[b_name].append((_time, _t_info))

        for kf in data.get("keyframes", []):
            time = start_frame + (kf.get("position", 0) * fps_scale)
            part_name = kf.get("part_name", "").strip().lower()
            if not part_name: part_name = "root"
            values = kf.get("values", {})

            # Transition info for easing pass
            trans_type = values.get("TRANSITION", "linear")
            t_info = {
                "type": trans_type,
                "ease_in": (values.get("EASE_IN_X", 1.0), values.get("EASE_IN_Y", 0.0)),
                "ease_out": (values.get("EASE_OUT_X", 0.0), values.get("EASE_OUT_Y", 1.0))
            }
            
            if part_name in config.get("bones", {}):
                b_cfg = config["bones"][part_name]
                if "target_rot" in b_cfg: _add_trans(b_cfg["target_rot"], time, t_info)
                if "target_pos_scl" in b_cfg: _add_trans(b_cfg["target_pos_scl"], time, t_info)
                if "target" in b_cfg: _add_trans(b_cfg["target"], time, t_info)

            if part_name in config.get("bend_targets", {}):
                _add_trans(config["bend_targets"][part_name], time, t_info)

            # --- Bone Handling ---
            if part_name in config.get("bones", {}):
                bone_cfg = config["bones"][part_name]
                if "target_rot" in bone_cfg:
                    bone_rot = arm.pose.bones.get(bone_cfg["target_rot"])
                    if bone_rot:
                        handler = configs.HANDLERS.get(bone_cfg.get("handler_rot", "standard"))
                        if handler: handler(bone_rot, values, bone_cfg, time)
                if "target_pos_scl" in bone_cfg:
                    bone_ps = arm.pose.bones.get(bone_cfg["target_pos_scl"])
                    if bone_ps:
                        handler = configs.HANDLERS.get(bone_cfg.get("handler_pos_scl", "pos_scl"))
                        if handler: handler(bone_ps, values, bone_cfg, time)

            # --- Bend Handling ---
            if part_name in config.get("bend_targets", {}):
                target_bone_name = config["bend_targets"][part_name]
                bone_lower = arm.pose.bones.get(target_bone_name)
                if bone_lower:
                    bx = math.radians(values.get("BEND_ANGLE_X", 0))
                    by = math.radians(values.get("BEND_ANGLE_Y", 0))
                    bz = math.radians(values.get("BEND_ANGLE_Z", 0))
                    bone_lower.rotation_mode = 'QUATERNION'
                    bone_lower.rotation_quaternion = Euler((bx, by, bz), 'XYZ').to_quaternion()
                    bone_lower.keyframe_insert("rotation_quaternion", frame=time)

        # --- Easing ---
        if arm.animation_data and arm.animation_data.action:
            action = arm.animation_data.action
            for fcurve in action.fcurves:
                m = re.match(r'pose\.bones\["([^"]+)"\]\.', fcurve.data_path)
                if m and m.group(1) in kf_trans_map:
                    self.apply_interpolation(fcurve, kf_trans_map[m.group(1)])

        # --- Set Mapping Mode ---
        if "logic" in arm.pose.bones:
            arm.pose.bones["logic"]["mi_mapping_mode"] = 1.0

        # --- Auto-detect Alex (slim) mode ---
        model_info = data.get("model", {})
        state = model_info.get("state", {})
        if state.get("type") == "slim" and "prop.misc" in arm.pose.bones:
            arm.pose.bones["prop.misc"]["alex"] = 1

        self.report({'INFO'}, "Imported successfully via Rig2 + mi2bl core")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MI_OT_ImportConfirmDialog(bpy.types.Operator):
    """Warning dialog for non-character animations"""
    bl_idname = "mi.import_confirm_dialog"
    bl_label = "Import Warning"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty()
    op_type: bpy.props.StringProperty()

    def execute(self, context):
        if self.op_type == "OBJECT":
            bpy.ops.mi.import_object_action(filepath=self.filepath, confirmed=True)
        else:
            bpy.ops.mi.import_action(filepath=self.filepath, confirmed=True)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Advanced mi2bl features require both addons to be active.", icon='INFO')
        col.label(text="Character animations are now handled exclusively by Rig2.")
