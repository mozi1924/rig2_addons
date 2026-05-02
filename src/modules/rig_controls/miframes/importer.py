import bpy
import math
import sys
import os
import re
from mathutils import Euler
from ....services.miframes_service import get_miframes_backend_service
from ....core.utils import refresh_rig_drivers
from ....licensing.ui_gate import report_blocking_license_warnings

# Rig2 depends on mi2bl for the core MI parsing and easing logic.
# This fulfills the "Rig2 needs mi2bl" requirement and merges duplicate code.
try:
    # In Blender, we can try to reach the mi2bl package
    from mi2bl.src.utils import core
    MIBaseImporter = core.MIBaseImporter
    apply_mi_transition = core.apply_mi_transition
except (ImportError, ModuleNotFoundError):
    # Fallback if mi2bl is not found in path (Blender dev or missing addon)
    try:
        # Try local fallback if developing in the same workspace
        # (This is just for survival during refactoring)
        sys.path.append(os.path.join(os.path.dirname(__file__), "../../../../../mi2bl"))
        from src.utils import core
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


_miframes_plan_ops = get_miframes_backend_service().plan_miframes_keyframe_ops
_miframes_model_config = get_miframes_backend_service().get_model_config


def _apply_bend_values(bone, values, time):
    bx = math.radians(values.get("BEND_ANGLE_X", 0))
    by = math.radians(values.get("BEND_ANGLE_Y", 0))
    bz = math.radians(values.get("BEND_ANGLE_Z", 0))
    bone.rotation_mode = 'QUATERNION'
    bone.rotation_quaternion = Euler((bx, by, bz), 'XYZ').to_quaternion()
    bone.keyframe_insert("rotation_quaternion", frame=time)


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
        if report_blocking_license_warnings(self):
            return {"CANCELLED"}

        miframes_service = get_miframes_backend_service()
        if not miframes_service.is_feature_unlocked():
            self.report({'ERROR'}, miframes_service.get_lock_reason())
            return {'CANCELLED'}

        arm = context.active_object
        if not arm or arm.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select the Rig2 Armature")
            return {'CANCELLED'}

        if not hasattr(arm, "rig2_props"):
            self.report({'ERROR'}, "Rig2 properties missing.")
            return {'CANCELLED'}

        char_index = getattr(arm.rig2_props, "mi_char_index", 0)
        data, err = self.check_file(self.filepath, char_index=char_index)
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
        config = _miframes_model_config(model_key)
        if not config:
            self.report({'ERROR'}, f"Model config '{model_key}' not found.")
            return {'CANCELLED'}

        tempo, fps_current, fps_scale = self.setup_scene(
            context, data, 
            arm.rig2_props.mi_start_frame, 
            arm.rig2_props.mi_adjust_end_frame
        )
        start_frame = arm.rig2_props.mi_start_frame

        plan = _miframes_plan_ops(data, config, start_frame, fps_scale)
        kf_trans_map = plan.get("transitions", {})

        for operation in plan.get("operations", []):
            time = operation["time"]
            values = operation["values"]
            bone_name = operation["bone_name"]
            handler_kind = operation["handler_kind"]
            handler_name = operation.get("handler_name", "")

            pose_bone = arm.pose.bones.get(bone_name)
            if not pose_bone:
                continue

            if handler_kind == "bend":
                _apply_bend_values(pose_bone, values, time)
                continue

            part_name = operation["part_name"]
            bone_cfg = config.get("bones", {}).get(part_name, {})
            handler = configs.HANDLERS.get(handler_name)
            if handler:
                handler(pose_bone, values, bone_cfg, time)

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

        refresh_rig_drivers(arm, context=context)

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
