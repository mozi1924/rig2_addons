import bpy

from ...core.utils import is_rig2_armature


def _target_rig_poll(_self, obj):
    return is_rig2_armature(obj)


class Rig2FaceCapSettings(bpy.types.PropertyGroup):
    listen_host: bpy.props.StringProperty(
        name="Host",
        description="Local interface used by the face capture WebSocket receiver",
        default="0.0.0.0",
    )

    listen_port: bpy.props.IntProperty(
        name="Port",
        description="Local port used by the face capture WebSocket receiver",
        default=9000,
        min=1,
        max=65535,
    )

    target_rig: bpy.props.PointerProperty(
        name="Target Rig",
        description="Rig2 armature that should receive incoming face capture data",
        type=bpy.types.Object,
        poll=_target_rig_poll,
    )


def get_face_cap_settings(scene):
    return getattr(scene, "rig2_face_cap_settings", None)


classes = (
    Rig2FaceCapSettings,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"Rig2 FaceCap register error for {cls.__name__}: {exc}")

    if not hasattr(bpy.types.Scene, "rig2_face_cap_settings"):
        bpy.types.Scene.rig2_face_cap_settings = bpy.props.PointerProperty(
            type=Rig2FaceCapSettings,
        )


def unregister():
    if hasattr(bpy.types.Scene, "rig2_face_cap_settings"):
        del bpy.types.Scene.rig2_face_cap_settings

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
