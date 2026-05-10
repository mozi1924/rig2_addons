import json
import math
from pathlib import Path

import bpy

from ...core.utils import is_rig2_armature
from ...i18n import format_text as _f
from .mapping import (
    DEFAULT_PRESET_ID,
    load_preset_definition,
    mapping_entries_to_export_bones,
    mapping_entries_to_export_name_map,
    mapping_entries_to_rotation_axis_signs,
    mapping_entries_to_transform_axis_signs,
    normalize_mapping_entries,
)
from .shared import get_action, get_keyed_frames
GECKOLIB_FORMAT_VERSION = "1.8.0"
BLOCKBENCH_UNITS_PER_METER = 8.0
EXPORT_FORMAT_ITEMS = (
    ("BASIC", "MI Names", "Export with the original MI bone names"),
    ("MAPPED", "Preset Names", "Export with the mapped export names from the chosen preset"),
)

def _resolve_mapping_entries(mapping_entries=None):
    resolved = normalize_mapping_entries(mapping_entries)
    if resolved:
        return resolved

    preset = load_preset_definition(DEFAULT_PRESET_ID)
    return normalize_mapping_entries(preset["entries"] if preset else [])


def _get_export_pose_bones(armature, mapping_entries):
    pose_bones = armature.pose.bones
    export_pairs = []
    missing_bones = []

    for mi_bone_name in mapping_entries_to_export_bones(mapping_entries):
        pose_bone = pose_bones.get(mi_bone_name)
        if pose_bone:
            export_pairs.append((mi_bone_name, pose_bone))
        else:
            missing_bones.append(mi_bone_name)

    return export_pairs, missing_bones


def get_export_animation_name(action, requested_name):
    name = (requested_name or "").strip()
    if name:
        return name
    return action.name if action else "animation"


def _format_time_key(seconds_value):
    text = f"{seconds_value:.4f}".rstrip("0").rstrip(".")
    if not text:
        return "0.0"
    if "." not in text:
        return f"{text}.0"
    return text


def _normalize_number(value, precision=4):
    rounded = round(float(value), precision)
    return 0.0 if abs(rounded) < 10 ** (-precision) else rounded


def _normalize_vector(values, precision=4):
    return [_normalize_number(value, precision=precision) for value in values]


def _apply_signed_scale(value, sign):
    return 1.0 + ((value - 1.0) * sign)


def _get_pose_bone_local_and_rest_matrices(pose_bone):
    if pose_bone.parent:
        pose_local = pose_bone.parent.matrix.inverted_safe() @ pose_bone.matrix
        rest_local = pose_bone.parent.bone.matrix_local.inverted_safe() @ pose_bone.bone.matrix_local
    else:
        pose_local = pose_bone.matrix.copy()
        rest_local = pose_bone.bone.matrix_local.copy()

    return pose_local, rest_local


def _sample_pose_bone_local_delta_matrix(pose_bone):
    pose_local, rest_local = _get_pose_bone_local_and_rest_matrices(pose_bone)
    return rest_local.inverted_safe() @ pose_local


def ensure_animation_json_suffix(filepath):
    if filepath.lower().endswith(".animation.json"):
        return filepath
    return f"{filepath}.animation.json"


def default_export_filepath(action):
    if bpy.data.is_saved:
        directory = Path(bpy.path.abspath("//"))
    else:
        directory = Path.home()

    action_name = action.name if action else "animation"
    filename = f"{bpy.path.clean_name(action_name)}.animation.json"
    return str(directory / filename)


def _sample_pose_bone_local_delta_components(pose_bone, previous_euler=None):
    location, rotation, scale = _sample_pose_bone_local_delta_matrix(pose_bone).decompose()
    euler = rotation.to_euler("XYZ")
    if previous_euler is not None:
        euler.make_compatible(previous_euler)
    return location, euler, scale


def _build_geckolib_animation(context, armature, action, export_format, animation_name, mapping_entries=None):
    mapping_entries = _resolve_mapping_entries(mapping_entries)
    export_pairs, missing_bones = _get_export_pose_bones(armature, mapping_entries)
    if not export_pairs:
        return None, _f("No mapped MI bones were found on this rig")

    source_names = {bone_name for bone_name, _ in export_pairs}
    frames = get_keyed_frames(action, source_names)
    if not frames:
        return None, _f("No keyframes found on the mapped MI bones")

    rotation_axis_signs = mapping_entries_to_rotation_axis_signs(mapping_entries)
    transform_axis_signs = mapping_entries_to_transform_axis_signs(mapping_entries)
    export_name_map = mapping_entries_to_export_name_map(mapping_entries)
    missing_name_mappings = []
    previous_eulers = {}
    bones_payload = {}

    scene = context.scene
    fps_base = scene.render.fps_base if scene.render.fps_base else 1.0
    fps = scene.render.fps / fps_base if scene.render.fps else 24.0
    first_frame = frames[0]
    original_frame = scene.frame_current

    try:
        for frame in frames:
            scene.frame_set(frame)
            context.view_layer.update()

            time_key = _format_time_key((frame - first_frame) / fps)

            for source_name, pose_bone in export_pairs:
                previous_euler = previous_eulers.get(source_name)
                location, euler, scale = _sample_pose_bone_local_delta_components(
                    pose_bone=pose_bone,
                    previous_euler=previous_euler,
                )
                previous_eulers[source_name] = euler.copy()

                rotation_signs = rotation_axis_signs.get(source_name, {"X": 1.0, "Y": 1.0, "Z": 1.0})
                rotation_values = _normalize_vector([
                    math.degrees(euler.x) * rotation_signs["X"],
                    math.degrees(euler.y) * rotation_signs["Y"],
                    math.degrees(euler.z) * rotation_signs["Z"],
                ])

                transform_signs = transform_axis_signs.get(source_name, {"X": 1.0, "Y": 1.0, "Z": 1.0})
                position_values = _normalize_vector([
                    location.x * BLOCKBENCH_UNITS_PER_METER * transform_signs["X"],
                    location.y * BLOCKBENCH_UNITS_PER_METER * transform_signs["Y"],
                    location.z * BLOCKBENCH_UNITS_PER_METER * transform_signs["Z"],
                ])
                scale_values = _normalize_vector([
                    _apply_signed_scale(scale.x, transform_signs["X"]),
                    _apply_signed_scale(scale.y, transform_signs["Y"]),
                    _apply_signed_scale(scale.z, transform_signs["Z"]),
                ])

                export_name = source_name
                if export_format == "MAPPED":
                    export_name = export_name_map.get(source_name, source_name)
                    if source_name not in export_name_map:
                        missing_name_mappings.append(source_name)

                bone_payload = bones_payload.setdefault(export_name, {"rotation": {}, "position": {}, "scale": {}})
                bone_payload["rotation"][time_key] = rotation_values
                bone_payload["position"][time_key] = position_values
                bone_payload["scale"][time_key] = scale_values
    finally:
        scene.frame_set(original_frame)
        context.view_layer.update()

    payload = {
        "format_version": GECKOLIB_FORMAT_VERSION,
        "animations": {
            animation_name: {
                "animation_length": _normalize_number((frames[-1] - first_frame) / fps),
                "bones": bones_payload,
            }
        },
    }

    metadata = {
        "bone_count": len(bones_payload),
        "frame_count": len(frames),
        "missing_bones": missing_bones,
        "missing_name_mappings": sorted(set(missing_name_mappings)),
    }
    return payload, metadata


def export_geckolib_json(context, filepath, export_format="BASIC", animation_name="", mapping_entries=None):
    armature = context.active_object
    if not is_rig2_armature(armature):
        return False, _f("Please select a Rig2 armature")

    action = get_action(armature)
    if not action:
        return False, _f("No active action found on the Rig2 armature")

    resolved_animation_name = get_export_animation_name(action, animation_name)
    payload, result = _build_geckolib_animation(
        context=context,
        armature=armature,
        action=action,
        export_format=export_format,
        animation_name=resolved_animation_name,
        mapping_entries=mapping_entries,
    )
    if payload is None:
        if result == _f("No keyframes found on the mapped MI bones"):
            result += _f(". Bake Base -> MI first, then export.")
        return False, result

    output_path = Path(ensure_animation_json_suffix(filepath))
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    message = _f(
        "Exported GeckoLib JSON with {bone_count} bones and {frame_count} sampled frames",
        bone_count=result["bone_count"],
        frame_count=result["frame_count"],
    )
    if export_format == "MAPPED" and result["missing_name_mappings"]:
        message += _f(
            " ({count} preset names missing, kept MI names)",
            count=len(result["missing_name_mappings"]),
        )
    if result["missing_bones"]:
        message += _f(
            " ({count} mapped bones missing on rig)",
            count=len(result["missing_bones"]),
        )

    return True, message
