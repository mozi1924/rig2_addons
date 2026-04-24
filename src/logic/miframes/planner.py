"""
Pure planning helpers for .miframes import.

This module is intentionally Blender-free so it can be migrated to
native backends later.
"""


def build_transition_info(values):
    return {
        "type": values.get("TRANSITION", "linear"),
        "ease_in": (values.get("EASE_IN_X", 1.0), values.get("EASE_IN_Y", 0.0)),
        "ease_out": (values.get("EASE_OUT_X", 0.0), values.get("EASE_OUT_Y", 1.0)),
    }


def normalize_part_name(part_name):
    normalized = str(part_name or "").strip().lower()
    return normalized if normalized else "root"


def plan_miframes_keyframe_ops(data, config, start_frame, fps_scale):
    """
    Convert parsed miframes payload into keyframe-ready operation plans.

    Returns:
    {
      "operations": [
        {
          "time": float,
          "part_name": str,
          "values": dict,
          "bone_name": str,
          "handler_kind": "rot" | "pos_scl" | "bend",
          "handler_name": str
        }
      ],
      "transitions": {bone_name: [(time, transition_info), ...]}
    }
    """
    operations = []
    transitions = {}
    bones_cfg = config.get("bones", {})
    bend_cfg = config.get("bend_targets", {})

    for keyframe in data.get("keyframes", []):
        time = start_frame + (keyframe.get("position", 0) * fps_scale)
        part_name = normalize_part_name(keyframe.get("part_name"))
        values = keyframe.get("values", {})
        transition = build_transition_info(values)

        bone_cfg = bones_cfg.get(part_name)
        if bone_cfg:
            for target_key in ("target_rot", "target_pos_scl", "target"):
                bone_name = bone_cfg.get(target_key)
                if bone_name:
                    transitions.setdefault(bone_name, []).append((time, transition))

            rot_target = bone_cfg.get("target_rot")
            if rot_target:
                operations.append(
                    {
                        "time": time,
                        "part_name": part_name,
                        "values": values,
                        "bone_name": rot_target,
                        "handler_kind": "rot",
                        "handler_name": bone_cfg.get("handler_rot", "standard"),
                    }
                )

            pos_scl_target = bone_cfg.get("target_pos_scl")
            if pos_scl_target:
                operations.append(
                    {
                        "time": time,
                        "part_name": part_name,
                        "values": values,
                        "bone_name": pos_scl_target,
                        "handler_kind": "pos_scl",
                        "handler_name": bone_cfg.get("handler_pos_scl", "pos_scl"),
                    }
                )

        bend_target = bend_cfg.get(part_name)
        if bend_target:
            transitions.setdefault(bend_target, []).append((time, transition))
            operations.append(
                {
                    "time": time,
                    "part_name": part_name,
                    "values": values,
                    "bone_name": bend_target,
                    "handler_kind": "bend",
                    "handler_name": "bend",
                }
            )

    return {"operations": operations, "transitions": transitions}

