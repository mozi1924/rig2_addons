from ...core.constants import INTERNAL_KEYS
from ...core.utils import is_rig2_armature


def is_face_cap_enabled(obj):
    if not is_rig2_armature(obj):
        return False

    pose = getattr(obj, "pose", None)
    if not pose:
        return False

    logic_bone = pose.bones.get("logic")
    face_bone = pose.bones.get("Face_BlendShapes")
    if not logic_bone or not face_bone:
        return False

    return float(logic_bone.get("face_cap", 0.0)) >= 0.999


def get_target_props(face_bone):
    return [key for key in face_bone.keys() if key not in INTERNAL_KEYS]
