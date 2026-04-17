import bpy
import re

# ─── MI → FK Bone Mapping ───────────────────────────────────────────────────
# Maps MI bone names to their corresponding FK bone names.
# Since the parent-child hierarchies differ between MI and FK chains,
# we must bake world-space transforms (not just copy local transforms).

MI_TO_FK_MAP = {
    "MI_Root":          "Root",
    "MI_Head":          "Head root",
    "MI_arm.R":         "Shoulder.R",
    "MI_arm.upper.R":   "arm.fk.upper.R",
    "MI_arm.lower.R":   "arm.fk.lower.R",
    "MI_wrist.R":       "arm.wrist.ctrl.R",
    "MI_arm.L":         "Shoulder.L",
    "MI_arm.upper.L":   "arm.fk.upper.L",
    "MI_arm.lower.L":   "arm.fk.lower.L",
    "MI_wrist.L":       "arm.wrist.ctrl.L",
    "MI_Body Upper":    "Body Upper",
    "MI_Body Lower":    "Hip",
    "MI_leg.R":         "leg.root.R",
    "MI_leg.upper.R":   "leg.fk.upper.R",
    "MI_leg.lower.R":   "leg.fk.lower.R",
    "MI_ankle.R":       "ankle_crontrol.R",
    "MI_leg.L":         "leg.root.L",
    "MI_leg.upper.L":   "leg.fk.upper.L",
    "MI_leg.lower.L":   "leg.fk.lower.L",
    "MI_ankle.L":       "ankle_crontrol.L",
}

# IK/FK switch properties: set to 0.0 = FK mode
IK_FK_PROPS = [
    "arm-L-fk-ik",
    "arm-R-fk-ik",
    "leg-L-fk-ik",
    "leg-R-fk-ik",
]


def _get_bone_depth(pose_bone):
    """Get the hierarchy depth of a pose bone (0 = root)."""
    depth = 0
    b = pose_bone
    while b.parent:
        depth += 1
        b = b.parent
    return depth


def _get_keyed_frames(arm):
    """Collect all unique keyframe frame numbers from MI bones in the action."""
    if not arm.animation_data or not arm.animation_data.action:
        return []

    action = arm.animation_data.action
    mi_bone_names = set(MI_TO_FK_MAP.keys())
    frames = set()

    for fcurve in action.fcurves:
        m = re.match(r'pose\.bones\["([^"]+)"\]\.', fcurve.data_path)
        if m and m.group(1) in mi_bone_names:
            for kp in fcurve.keyframe_points:
                frames.add(int(kp.co.x))

    if not frames:
        return []
    
    # Bake EVERY frame to prevent motion loss on >180 degree spins
    min_frame = min(frames)
    max_frame = max(frames)
    
    return list(range(int(min_frame), int(max_frame) + 1))


def _get_mi_fcurves(action):
    """Get all fcurves that belong to MI bones."""
    mi_bone_names = set(MI_TO_FK_MAP.keys())
    results = []
    for fcurve in action.fcurves:
        m = re.match(r'pose\.bones\["([^"]+)"\]\.', fcurve.data_path)
        if m and m.group(1) in mi_bone_names:
            results.append(fcurve)
    return results


def _remove_fcurves_by_path_prefixes(action, prefixes):
    """Remove fcurves whose data_path starts with any of the provided prefixes."""
    prefixes = tuple(prefixes)
    to_remove = [fc for fc in action.fcurves if fc.data_path.startswith(prefixes)]
    for fc in to_remove:
        action.fcurves.remove(fc)


def _remove_fcurves_by_exact_paths(action, data_paths):
    """Remove fcurves whose data_path exactly matches one of the provided paths."""
    paths = set(data_paths)
    to_remove = [fc for fc in action.fcurves if fc.data_path in paths]
    for fc in to_remove:
        action.fcurves.remove(fc)


def _set_constraints_muted(constraints, mute):
    """Mute or unmute a constraint list in-place."""
    for constraint in constraints:
        constraint.mute = mute


def _solve_fk_pose_matrix(context, fk_bone, target_matrix, max_passes=3):
    """
    Solve a target armature-space matrix for an FK control under its final FK constraints.

    Blender's pose-bone matrix setter computes channels against the parent/rest
    relationship, but it does not automatically compensate for other active FK
    constraints that still run after MI mapping is disabled. For bones like
    Body Upper and Head root, a one-shot matrix assignment leaves those
    constraints double-applying motion. To counter that, we:
    1. Temporarily mute the always-on constraints.
    2. Solve a provisional matrix.
    3. Re-enable the constraints and measure the residual error.
    4. Pre-compensate the provisional matrix by that measured constraint delta.

    A couple of passes is enough for the Rig2 control rig and keeps the bake
    deterministic and frame-accurate.
    """
    active_constraints = [
        constraint for constraint in fk_bone.constraints
        if not constraint.mute and getattr(constraint, "influence", 0.0) > 1e-6
    ]
    desired_matrix = target_matrix.copy()

    for _ in range(max_passes):
        _set_constraints_muted(active_constraints, True)
        context.view_layer.update()

        fk_bone.matrix = desired_matrix
        context.view_layer.update()

        _set_constraints_muted(active_constraints, False)
        context.view_layer.update()

        solved_matrix = fk_bone.matrix.copy()
        error_angle = solved_matrix.to_quaternion().rotation_difference(target_matrix.to_quaternion()).angle
        error_loc = (solved_matrix.to_translation() - target_matrix.to_translation()).length
        if error_angle < 1e-6 and error_loc < 1e-6:
            break

        correction = solved_matrix @ target_matrix.inverted()
        desired_matrix = correction.inverted() @ desired_matrix


def bake_mi_to_fk(context):
    """
    Bake world-space transforms from MI bones onto FK bones,
    then clean up MI keyframes and switch all limbs to FK mode.
    
    Returns (success: bool, message: str)
    """
    arm = context.active_object
    if not arm or arm.type != 'ARMATURE':
        return False, "No armature selected"

    if not arm.animation_data or not arm.animation_data.action:
        return False, "No animation data / action on the armature"

    pose_bones = arm.pose.bones
    action = arm.animation_data.action

    # --- 1. Validate that the bones exist ---
    valid_pairs = []
    for mi_name, fk_name in MI_TO_FK_MAP.items():
        mi_bone = pose_bones.get(mi_name)
        fk_bone = pose_bones.get(fk_name)
        if mi_bone and fk_bone:
            valid_pairs.append((mi_name, fk_name, mi_bone, fk_bone))

    if not valid_pairs:
        return False, "No matching MI/FK bone pairs found in the armature"

    # --- 2. Collect all keyframe times from MI bones ---
    frames = _get_keyed_frames(arm)
    if not frames:
        return False, "No keyframes found on MI bones"

    # --- 3. Group FK bones by hierarchy depth for correct parent-first processing ---
    depth_groups = {}
    for item in valid_pairs:
        fk_bone = item[3]
        depth = _get_bone_depth(fk_bone)
        depth_groups.setdefault(depth, []).append(item)

    sorted_depths = sorted(depth_groups.keys())

    # --- 4. Sample MI matrices while MI mapping is still active ---
    scene = context.scene
    original_frame = scene.frame_current
    mi_world_samples = {}

    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()
        mi_world_samples[frame] = {}
        for mi_name, fk_name, mi_bone, fk_bone in valid_pairs:
            mi_world_samples[frame][mi_name] = mi_bone.matrix.copy()

    # --- 5. Switch to the final FK rig state before solving FK keys ---
    if "prop.limbs" in pose_bones:
        limbs_bone = pose_bones["prop.limbs"]
        for prop_name in IK_FK_PROPS:
            if prop_name in limbs_bone:
                limbs_bone[prop_name] = 0.0

    # Turn on head_inherit_rotation for accurate head transformation
    if "prop.head" in pose_bones:
        head_bone = pose_bones["prop.head"]
        if "head_inherit_rotation" in head_bone:
            head_bone["head_inherit_rotation"] = 1.0

    if "logic" in pose_bones:
        logic_bone = pose_bones["logic"]
        if "mi_mapping_mode" in logic_bone:
            logic_bone["mi_mapping_mode"] = 0.0

    # Ensure all FK bones are operating in QUATERNION mode before solving their channels.
    for mi_name, fk_name, mi_bone, fk_bone in valid_pairs:
        fk_bone.rotation_mode = 'QUATERNION'

    # Force depsgraph update so we are solving against the real FK constraint stack.
    context.view_layer.update()

    # --- 6. Remove old FK keys on the target controls, then solve frame by frame ---
    fk_bones = [fk_bone for _, _, _, fk_bone in valid_pairs]
    _remove_fcurves_by_path_prefixes(
        action,
        [f'pose.bones["{fk_bone.name}"].' for fk_bone in fk_bones],
    )
    previous_quats = {}

    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()

        for depth in sorted_depths:
            for mi_name, fk_name, mi_bone, fk_bone in depth_groups[depth]:
                target_matrix = mi_world_samples[frame][mi_name]
                _solve_fk_pose_matrix(context, fk_bone, target_matrix)

        for mi_name, fk_name, mi_bone, fk_bone in valid_pairs:
            current_quat = fk_bone.rotation_quaternion.copy()
            if fk_name in previous_quats:
                current_quat.make_compatible(previous_quats[fk_name])
                fk_bone.rotation_quaternion = current_quat
            previous_quats[fk_name] = current_quat.copy()

            fk_bone.keyframe_insert("rotation_quaternion", frame=frame)
            fk_bone.keyframe_insert("location", frame=frame)
            fk_bone.keyframe_insert("scale", frame=frame)

    context.view_layer.update()

    # --- 7. Remove ALL keyframes from MI bones ---
    mi_fcurves = _get_mi_fcurves(action)
    for fc in mi_fcurves:
        action.fcurves.remove(fc)

    # --- 8. Reset MI bones to rest pose ---
    for mi_name, fk_name, mi_bone, fk_bone in valid_pairs:
        mi_bone.rotation_mode = 'QUATERNION'
        mi_bone.rotation_quaternion = (1, 0, 0, 0)
        mi_bone.location = (0, 0, 0)
        mi_bone.scale = (1, 1, 1)

    # --- 9. Keyframe the bake-state props at the first frame ---
    if frames:
        first_frame = frames[0]

        if "prop.limbs" in pose_bones:
            limbs_bone = pose_bones["prop.limbs"]
            _remove_fcurves_by_exact_paths(
                action,
                [f'pose.bones["prop.limbs"]["{prop_name}"]' for prop_name in IK_FK_PROPS],
            )
            for prop_name in IK_FK_PROPS:
                if prop_name in limbs_bone:
                    limbs_bone[prop_name] = 0.0
                    limbs_bone.keyframe_insert(
                        data_path=f'["{prop_name}"]',
                        frame=first_frame
                    )
        
        if "prop.head" in pose_bones:
            head_bone = pose_bones["prop.head"]
            if "head_inherit_rotation" in head_bone:
                _remove_fcurves_by_exact_paths(
                    action,
                    ['pose.bones["prop.head"]["head_inherit_rotation"]'],
                )
                head_bone["head_inherit_rotation"] = 1.0
                head_bone.keyframe_insert(
                    data_path='["head_inherit_rotation"]',
                    frame=first_frame
                )

        if "logic" in pose_bones:
            logic_bone = pose_bones["logic"]
            if "mi_mapping_mode" in logic_bone:
                _remove_fcurves_by_exact_paths(
                    action,
                    ['pose.bones["logic"]["mi_mapping_mode"]'],
                )
                logic_bone["mi_mapping_mode"] = 0.0
                logic_bone.keyframe_insert(
                    data_path='["mi_mapping_mode"]',
                    frame=first_frame
                )

    # Restore original frame
    scene.frame_set(original_frame)
    context.view_layer.update()

    return True, f"Baked {len(frames)} frames across {len(valid_pairs)} bone pairs to FK"


class MI_OT_BakeToFK(bpy.types.Operator):
    """Bake MI bone animations to FK bones, clear MI keyframes, and switch to FK mode"""
    bl_idname = "mi.bake_to_fk"
    bl_label = "Bake MI → FK?"
    bl_description = (
        "Bake world-space transforms from MI bones to FK bones, "
        "remove MI keyframes, and switch all limbs to FK mode"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        success, msg = bake_mi_to_fk(context)
        if success:
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
