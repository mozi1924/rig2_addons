import bpy
from bpy.props import EnumProperty, PointerProperty

# Property mapping and friendly names for Rig Controls
PROPERTY_MAP = {
    "limbs": [
        "arm-L-fk-ik", "arm-L-wrist-ik", "arm-R-fk-ik", "arm-R-wrist-ik",
        "arm-world-ik", "ik-stretch.arm", "ik-stretch.leg", "leg-L-fk-ik", "leg-R-fk-ik"
    ],
    "head": [
        "lash", "jaw", "eyebrow_width", "brow_auto_rotation", "mouth_shape",
        "neck_length", "eye_tracker", "Tongue", "enable_neck", "eyebrow",
        "inherit_rotation", "layout_mode", "panel_to_face"
    ],
    "misc": [
        "alex", "hands", "feet_style"
    ],
    "performance": [
        "enable_left_eye", "enable_right_eye", "enable_mouth",
        "render_body_boolen", "render_face_boolen", "view_body_boolen", "view_face_boolen",
        "render-subdivision", "view-subdivision"
    ]
}

FRIENDLY_NAMES = {
    # Limbs
    "arm-L-fk-ik": "Arm L (FK/IK)",
    "arm-R-fk-ik": "Arm R (FK/IK)",
    "arm-L-wrist-ik": "Wrist L Follow",
    "arm-R-wrist-ik": "Wrist R Follow",
    "leg-L-fk-ik": "Leg L (FK/IK)",
    "leg-R-fk-ik": "Leg R (FK/IK)",
    "arm-world-ik": "Arm World IK",
    "ik-stretch.arm": "Arm Stretch",
    "ik-stretch.leg": "Leg Stretch",

    # Head & Face
    "jaw": "Jaw Opening",
    "eyebrow_width": "Eyebrow Width",
    "brow_auto_rotation": "Brow Auto Rotate",
    "mouth_shape": "Mouth Shape",
    "neck_length": "Neck Length",
    "eye_tracker": "Eye Tracker",
    "Tongue": "Show Tongue",
    "enable_neck": "Enable Neck",
    "eyebrow": "Show Eyebrow",
    "inherit_rotation": "Inherit Rotation",
    "layout_mode": "Layout Mode",
    "panel_to_face": "Panel to Face",

    # Misc
    "alex": "Slim Arm (Alex)",
    "hands": "Hands",
    "feet_style": "Ankle/Feet Style",

    # Performance
    "enable_left_eye": "Left Eye",
    "enable_right_eye": "Right Eye",
    "enable_mouth": "Mouth",
    "view_body_boolen": "Viewport Body Boolean",
    "render_body_boolen": "Render Body Boolean",
    "view_face_boolen": "Viewport Face Boolean",
    "render_face_boolen": "Render Face Boolean",
    "view-subdivision": "Viewport Subdivision",
    "render-subdivision": "Render Subdivision",
}

def get_bone_val(bone_name, prop_name, default=0):
    obj = bpy.context.active_object
    if obj and bone_name in obj.pose.bones:
        return obj.pose.bones[bone_name].get(prop_name, default)
    return default

def set_bone_val(bone_name, prop_name, val):
    obj = bpy.context.active_object
    if obj and bone_name in obj.pose.bones:
        obj.pose.bones[bone_name][prop_name] = val

class Rig2ControlProperties(bpy.types.PropertyGroup):
    def get_lash(self): return int(get_bone_val("prop.head", "lash", 0))
    def set_lash(self, value): set_bone_val("prop.head", "lash", int(value))
    
    lash_enum: EnumProperty(
        name="Lash Style",
        items=[
            ('0', "None", ""), ('1', "Style 1", ""), ('2', "Style 2", ""),
            ('3', "Style 3", ""), ('4', "Style 4", ""), ('5', "Style 5", ""),
            ('6', "Style 6", ""),
        ],
        get=get_lash, set=set_lash
    )

    def get_feet(self):
        val = int(get_bone_val("prop.misc", "feet_style", 0))
        return val + 1

    def set_feet(self, value):
        set_bone_val("prop.misc", "feet_style", value - 1)

    feet_enum: EnumProperty(
        name="Feet Style",
        items=[
            ('-1', "None", ""), ('0', "Standard", ""), ('1', "Fancy Feet", ""),
        ],
        get=get_feet, set=set_feet
    )

    mirror_display: bpy.props.BoolProperty(
        name="Mirror",
        description="Mirror L/R property display order",
        default=False
    )

def register():
    bpy.utils.register_class(Rig2ControlProperties)
    bpy.types.Object.rig2_props = PointerProperty(type=Rig2ControlProperties)

def unregister():
    bpy.utils.unregister_class(Rig2ControlProperties)
    del bpy.types.Object.rig2_props
