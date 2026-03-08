import math
from mathutils import Euler, Vector

# Rig2 depends on mi2bl for the core MI constants and parsing logic.
try:
    from mi2bl.src.core import MI_SCALE, fix_mi_yz_swap, parse_mi_file_data
except (ImportError, ModuleNotFoundError):
    # Survive during loading if mi2bl is missing
    MI_SCALE = 1.0 / 16.0
    def fix_mi_yz_swap(v): return v
    def parse_mi_file_data(d): return d

# --- Specialized Bone Handlers (Rig2 Specific) ---

def handler_standard(bone, values, config, time):
    """Standard bone rotation using axis mapping and optional offsets."""
    axis_map = config.get("axis_map", {})
    axis_scale = config.get("axis_scale", {"X": 1.0, "Y": 1.0, "Z": 1.0})
    
    val_x = math.radians(values.get(axis_map.get("X", "ROT_X"), 0)) * axis_scale.get("X", 1.0)
    val_y = math.radians(values.get(axis_map.get("Y", "ROT_Y"), 0)) * axis_scale.get("Y", 1.0)
    val_z = math.radians(values.get(axis_map.get("Z", "ROT_Z"), 0)) * axis_scale.get("Z", 1.0)
    
    # Apply special offsets (e.g. for arms)
    offset = config.get("rotation_offset", (0, 0, 0))
    val_x += math.radians(offset[0])
    val_y += math.radians(offset[1])
    val_z += math.radians(offset[2])
    
    q = Euler((val_x, val_y, val_z), 'XYZ').to_quaternion()
    bone.rotation_mode = 'QUATERNION'
    bone.rotation_quaternion = q
    bone.keyframe_insert("rotation_quaternion", frame=time)

def handler_pos_scl(bone, values, config, time):
    """Position and Scale mapping."""
    pos_map = config.get("pos_map", {"X": "POS_X", "Y": "POS_Y", "Z": "POS_Z"})
    scl_map = config.get("scl_map", {"X": "SCA_X", "Y": "SCA_Y", "Z": "SCA_Z"})
    
    # Position
    has_pos = False
    v_pos = list(bone.location)
    for i, axis in enumerate(["X", "Y", "Z"]):
        key = pos_map.get(axis)
        if key in values:
            v_pos[i] = values[key] * MI_SCALE
            has_pos = True
            
    if has_pos:
        bone.location = (v_pos[0], v_pos[1], v_pos[2])
        bone.keyframe_insert("location", frame=time)

    # Scale
    has_scl = False
    v_scl = list(bone.scale)
    for i, axis in enumerate(["X", "Y", "Z"]):
        key = scl_map.get(axis)
        if key in values:
            v_scl[i] = values[key]
            has_scl = True

    if has_scl:
        bone.scale = (v_scl[0], v_scl[1], v_scl[2])
        bone.keyframe_insert("scale", frame=time)

HANDLERS = {
    "standard": handler_standard,
    "pos_scl": handler_pos_scl,
}

# --- Model Registry (Character Specifics) ---

RIG2_STEVE = {
    "name": "Rig2 Steve (MI Direct)",
    "bones": {
        "root": {
            "target_rot": "MI_Root",
            "target_pos_scl": "MI_Root",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
        },
        "head": {
            "target_rot": "MI_Head",
            "target_pos_scl": "MI_P_Head",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
        },
        "body": {
            "target_rot": "MI_Body Lower",
            "target_pos_scl": "MI_Body",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
        },
        "left_arm": {
            "target_rot": "MI_arm.upper.L",
            "target_pos_scl": "MI_arm.L",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
        },
        "right_arm": {
            "target_rot": "MI_arm.upper.R",
            "target_pos_scl": "MI_arm.R",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
        },
        "left_leg": {
            "target_rot": "MI_leg.upper.L",
            "target_pos_scl": "MI_leg.L",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
            "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0}
        },
        "right_leg": {
            "target_rot": "MI_leg.upper.R",
            "target_pos_scl": "MI_leg.R",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
            "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0}
        }
    },
    "bend_targets": {
        "left_arm": "MI_arm.lower.L",
        "right_arm": "MI_arm.lower.R",
        "left_leg": "MI_leg.lower.L",
        "right_leg": "MI_leg.lower.R",
        "body": "MI_Body Upper"
    }
}

MODELS = {
    "steve": RIG2_STEVE,
}
