import bpy
import json
import math
import sys
import os
import importlib
import re
from mathutils import Euler, Vector

# In a Blender package, we use relative imports.
# If we're run standalone (for dev), we fallback.
try:
    from . import configs
except (ImportError, ValueError):
    import configs

class MI_OT_ImportAction(bpy.types.Operator):
    """Import .miframes using a selected model configuration"""
    bl_idname = "mi.import_action"
    bl_label = "Load .miframes"
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath: return {'CANCELLED'}
            
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"JSON Load Failed: {str(e)}")
            return {'CANCELLED'}

        arm = context.active_object
        if not arm or arm.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select the Rig2 Armature")
            return {'CANCELLED'}

        # Get selected model from rig2_props
        if not hasattr(arm, "rig2_props") or not hasattr(arm.rig2_props, "mi_selected_model"):
            self.report({'ERROR'}, "Rig2 properties missing.")
            return {'CANCELLED'}
            
        model_key = arm.rig2_props.mi_selected_model
        config = configs.MODELS.get(model_key)
        if not config:
            self.report({'ERROR'}, f"Model config '{model_key}' not found.")
            return {'CANCELLED'}

        tempo = data.get("tempo", 24)
        fps_current = context.scene.render.fps
        # Conversion ratio from MI (tempo) to Blender (scene fps)
        fps_scale = fps_current / tempo

        # Handle frame_end conversion
        length = data.get("length", 0)
        # Assuming length is in deciframes, similar to position
        blender_end_frame = (length * 0.1) * fps_scale
        context.scene.frame_end = int(blender_end_frame)

        kf_trans_map = {}
        def _add_trans(b_name, _time, _t_info):
            if b_name not in kf_trans_map:
                kf_trans_map[b_name] = []
            kf_trans_map[b_name].append((_time, _t_info))

        for kf in data.get("keyframes", []):
            # Mine-imator deciframes (10x frames) -> Blender frames
            time = (kf.get("position", 0) * 0.1) * fps_scale
            part_name = kf.get("part_name", "").strip().lower()
            if not part_name: part_name = "root"
            values = kf.get("values", {})

            # --- Extract Transition Info ---
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

            # --- Primary Bone Handling ---
            if part_name in config.get("bones", {}):
                bone_cfg = config["bones"][part_name]
                
                # Handling rotation target
                if "target_rot" in bone_cfg:
                    bone_rot = arm.pose.bones.get(bone_cfg["target_rot"])
                    if bone_rot:
                        handler_name = bone_cfg.get("handler_rot", "standard")
                        handler_func = configs.HANDLERS.get(handler_name)
                        if handler_func:
                            handler_func(bone_rot, values, bone_cfg, time)
                
                # Handling position and scale target
                if "target_pos_scl" in bone_cfg:
                    bone_pos_scl = arm.pose.bones.get(bone_cfg["target_pos_scl"])
                    if bone_pos_scl:
                        handler_name = bone_cfg.get("handler_pos_scl", "pos_scl")
                        handler_func = configs.HANDLERS.get(handler_name)
                        if handler_func:
                            handler_func(bone_pos_scl, values, bone_cfg, time)
                            
                # Fallback for older configs
                if "target" in bone_cfg:
                    bone = arm.pose.bones.get(bone_cfg["target"])
                    if bone:
                        handler_name = bone_cfg.get("handler", "standard")
                        handler_func = configs.HANDLERS.get(handler_name)
                        if handler_func:
                            handler_func(bone, values, bone_cfg, time)

            # --- Bend (FK Lower) Handling ---
            if part_name in config.get("bend_targets", {}):
                target_bone_name = config["bend_targets"][part_name]
                bone_lower = arm.pose.bones.get(target_bone_name)
                
                if bone_lower:
                    bx = math.radians(values.get("BEND_ANGLE_X", 0))
                    by = math.radians(values.get("BEND_ANGLE_Z", 0))
                    bz = math.radians(values.get("BEND_ANGLE_Y", 0))
                    
                    q_bend = Euler((bx, by, bz), 'XYZ').to_quaternion()
                    bone_lower.rotation_mode = 'QUATERNION'
                    bone_lower.rotation_quaternion = q_bend
                    bone_lower.keyframe_insert("rotation_quaternion", frame=time)

        # --- Apply Interpolation & Bezier Ease ---
        if arm.animation_data and arm.animation_data.action:
            action = arm.animation_data.action
            for fcurve in action.fcurves:
                m = re.match(r'pose\.bones\["([^"]+)"\]\.', fcurve.data_path)
                if not m:
                    continue
                bone_name = m.group(1)
                if bone_name not in kf_trans_map:
                    continue
                    
                trans_list = kf_trans_map[bone_name]
                
                for i in range(1, len(fcurve.keyframe_points)):
                    kf0 = fcurve.keyframe_points[i - 1]
                    kf1 = fcurve.keyframe_points[i]
                    
                    target_time = kf1.co.x
                    
                    best_t_info = None
                    min_dist = 0.05
                    for t, info in trans_list:
                        dist = abs(t - target_time)
                        if dist < min_dist:
                            min_dist = dist
                            best_t_info = info
                            
                    if not best_t_info:
                        continue
                        
                    t_type = best_t_info["type"]
                    
                    if t_type == "instant":
                        kf0.interpolation = 'CONSTANT'
                    elif t_type == "linear":
                        kf0.interpolation = 'LINEAR'
                    elif t_type == "bezier":
                        kf0.interpolation = 'BEZIER'
                        dt = kf1.co.x - kf0.co.x
                        dv = kf1.co.y - kf0.co.y
                        
                        x1, y1 = best_t_info["ease_in"]
                        x2, y2 = best_t_info["ease_out"]
                        
                        kf0.handle_right_type = 'FREE'
                        kf1.handle_left_type = 'FREE'
                        
                        kf0.handle_right = (kf0.co.x + (x1 * dt), kf0.co.y + (y1 * dv))
                        kf1.handle_left = (kf0.co.x + (x2 * dt), kf0.co.y + (y2 * dv))
                    else:
                        kf0.interpolation = 'LINEAR'
                
                fcurve.update()

        # --- Auto setting mapping mode ---
        if "logic" in arm.pose.bones:
            bone_logic = arm.pose.bones["logic"]
            # To avoid type mismatch errors, delete if it exists as a non-float
            if "mi_mapping_mode" in bone_logic and not isinstance(bone_logic["mi_mapping_mode"], float):
                del bone_logic["mi_mapping_mode"]
            
            bone_logic["mi_mapping_mode"] = 1.0
            
            # Ensure proper UI metadata for the slider
            if "_RNA_UI" not in bone_logic:
                bone_logic["_RNA_UI"] = {}
            
            # Use dot notation or update with specific values to ensure float type
            ui_mgr = bone_logic.id_properties_ui("mi_mapping_mode")
            ui_mgr.update(
                min=0.0,
                max=1.0,
                soft_min=0.0,
                soft_max=1.0,
                default=0.0
            )

        self.report({'INFO'}, f"Imported '{config['name']}' animation successfully (tempo: {tempo}, scene FPS: {fps_current})")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

