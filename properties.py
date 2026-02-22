import bpy
from bpy.props import EnumProperty, PointerProperty

# 这个模块现在主要存储属性名称的映射关系，以及特殊的枚举映射
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
        "enable_left_eye", "enable_left_mouth", "enable_right_eye", "enable_right_mouth",
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

    # Performance/Optimization
    "enable_left_eye": "Left Eye",
    "enable_right_eye": "Right Eye",
    "enable_left_mouth": "Left Mouth",
    "enable_right_mouth": "Right Mouth",
    "view_body_boolen": "Viewport Body",
    "render_body_boolen": "Render Body",
    "view_face_boolen": "Viewport Face",
    "render_face_boolen": "Render Face",
    "view-subdivision": "Viewport Subdiv",
    "render-subdivision": "Render Subdiv",
}

# --- 辅助同步函数 ---
def get_bone_val(bone_name, prop_name, default=0):
    obj = bpy.context.active_object
    if obj and bone_name in obj.pose.bones:
        return obj.pose.bones[bone_name].get(prop_name, default)
    return default

def set_bone_val(bone_name, prop_name, val):
    obj = bpy.context.active_object
    if obj and bone_name in obj.pose.bones:
        obj.pose.bones[bone_name][prop_name] = val

# --- 用于 UI 增强的影子属性 ---
class Rig2Properties(bpy.types.PropertyGroup):
    
    def get_lash(self): return int(get_bone_val("prop.head", "lash", 0))
    def set_lash(self, value): set_bone_val("prop.head", "lash", int(value))
    
    lash_enum: EnumProperty(
        name="Lash Style",
        items=[
            ('0', "None", "No eyelashes"),
            ('1', "Style 1", ""),
            ('2', "Style 2", ""),
            ('3', "Style 3", ""),
            ('4', "Style 4", ""),
            ('5', "Style 5", ""),
            ('6', "Style 6", ""),
        ],
        get=get_lash, set=set_lash
    )

    def get_feet(self):
        val = int(get_bone_val("prop.misc", "feet_style", 0))
        # 根据用户手动指定的顺序: None(-1)=0, Standard(0)=1, Fancy(1)=2
        return val + 1

    def set_feet(self, value):
        # 索引转回数值: 0 -> -1, 1 -> 0, 2 -> 1
        set_bone_val("prop.misc", "feet_style", value - 1)

    feet_enum: EnumProperty(
        name="Feet Style",
        items=[
            ('-1', "None", "No ankles"),
            ('0', "Standard", "Standard ankles"),
            ('1', "Fancy Feet", "Detailed feet mode"),
        ],
        get=get_feet, set=set_feet
    )

def register():
    bpy.utils.register_class(Rig2Properties)
    bpy.types.Object.rig2_props = PointerProperty(type=Rig2Properties)

def unregister():
    bpy.utils.unregister_class(Rig2Properties)
    del bpy.types.Object.rig2_props
