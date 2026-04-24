"""
Model registry for miframes mapping.

Blender-independent data-only module.
"""

RIG2_STEVE = {
    "name": "Rig2 Steve (MI Direct)",
    "bones": {
        "root": {
            "target_rot": "MI_Root",
            "target_pos_scl": "MI_Root",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        },
        "head": {
            "target_rot": "MI_Head",
            "target_pos_scl": "MI_P_Head",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        },
        "body": {
            "target_rot": "MI_Body Lower",
            "target_pos_scl": "MI_Body",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        },
        "left_arm": {
            "target_rot": "MI_arm.upper.L",
            "target_pos_scl": "MI_arm.L",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        },
        "right_arm": {
            "target_rot": "MI_arm.upper.R",
            "target_pos_scl": "MI_arm.R",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        },
        "left_leg": {
            "target_rot": "MI_leg.upper.L",
            "target_pos_scl": "MI_leg.L",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
            "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0},
        },
        "right_leg": {
            "target_rot": "MI_leg.upper.R",
            "target_pos_scl": "MI_leg.R",
            "handler_rot": "standard",
            "handler_pos_scl": "pos_scl",
            "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
            "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0},
        },
    },
    "bend_targets": {
        "left_arm": "MI_arm.lower.L",
        "right_arm": "MI_arm.lower.R",
        "left_leg": "MI_leg.lower.L",
        "right_leg": "MI_leg.lower.R",
        "body": "MI_Body Upper",
    },
    "ik_targets": {
        "left_arm": {
            "ik_target_bone": "MI_arm.ik.target.L",
            "ik_pole_bone": "MI_arm.ik.pt.L",
            "logic_ik_prop": "mi_ik_arm.L",
        },
        "right_arm": {
            "ik_target_bone": "MI_arm.ik.target.R",
            "ik_pole_bone": "MI_arm.ik.pt.R",
            "logic_ik_prop": "mi_ik_arm.R",
        },
        "left_leg": {
            "ik_target_bone": "MI_leg.ik.target.L",
            "ik_pole_bone": "MI_leg.ik.pt.L",
            "logic_ik_prop": "mi_ik_leg.L",
        },
        "right_leg": {
            "ik_target_bone": "MI_leg.ik.target.R",
            "ik_pole_bone": "MI_leg.ik.pt.R",
            "logic_ik_prop": "mi_ik_leg.R",
        },
    },
}

MODELS = {"steve": RIG2_STEVE}


def get_models():
    return MODELS


def get_model_config(model_key):
    return MODELS.get(model_key)

