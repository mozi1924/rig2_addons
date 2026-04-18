import bpy

from ...core.utils import get_context_object, is_rig2_armature
from .runtime import get_runtime_service

INTERNAL_KEYS = {"_RNA_UI", "is_rig2"}


def _iter_face_actions(obj):
    animation_data = getattr(obj, "animation_data", None)
    if not animation_data:
        return

    seen = set()
    if animation_data.action:
        seen.add(animation_data.action)
        yield animation_data.action

    for track in animation_data.nla_tracks:
        for strip in track.strips:
            action = getattr(strip, "action", None)
            if action and action not in seen:
                seen.add(action)
                yield action


class RIG2_OT_FaceCapRestartServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_restart_server"
    bl_label = "Restart Face Capture Receiver"
    bl_description = "Restart the local WebSocket receiver using the current host and port"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, "Face Capture settings are not registered")
            return {"CANCELLED"}

        service = get_runtime_service()
        service.restart(settings.listen_host, settings.listen_port)
        self.report({"INFO"}, f"Face Capture receiver restarting on ws://{settings.listen_host}:{settings.listen_port}")
        return {"FINISHED"}


class RIG2_OT_FaceCapApplyNow(bpy.types.Operator):
    bl_idname = "rig2.face_cap_apply_now"
    bl_label = "Apply Cached Face Packet"
    bl_description = "Apply the latest received blendshape packet to enabled Rig2 armatures immediately"

    def execute(self, context):
        service = get_runtime_service()
        service.apply_latest_data()
        self.report({"INFO"}, f"Applied cached face packet to {service.count_enabled_rigs()} enabled rig(s)")
        return {"FINISHED"}


class RIG2_OT_FaceCapClearKeys(bpy.types.Operator):
    bl_idname = "rig2.face_cap_clear_keys"
    bl_label = "Clear Face Capture Keys"
    bl_description = "Delete all Face_BlendShapes custom property keyframes on the active Rig2 armature and reset them to zero"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = get_context_object(context)
        if not is_rig2_armature(obj):
            return False

        pose = getattr(obj, "pose", None)
        return bool(pose and pose.bones.get("Face_BlendShapes"))

    def execute(self, context):
        obj = get_context_object(context)
        face_bone = obj.pose.bones.get("Face_BlendShapes")
        if not face_bone:
            self.report({"ERROR"}, "Face_BlendShapes bone not found")
            return {"CANCELLED"}

        prop_names = [key for key in face_bone.keys() if key not in INTERNAL_KEYS]
        for prop_name in prop_names:
            face_bone[prop_name] = 0.0

        try:
            obj.update_tag(refresh={"OBJECT", "DATA"})
        except Exception:
            pass

        removed_curves = 0
        prefix = 'pose.bones["Face_BlendShapes"]["'
        for action in _iter_face_actions(obj):
            for fcurve in list(action.fcurves):
                if fcurve.data_path.startswith(prefix):
                    action.fcurves.remove(fcurve)
                    removed_curves += 1

        get_runtime_service().clear_cached_packet()

        if context.view_layer:
            context.view_layer.update()

        self.report({"INFO"}, f"Cleared {removed_curves} face capture f-curves and reset {len(prop_names)} blendshape values")
        return {"FINISHED"}


classes = (
    RIG2_OT_FaceCapRestartServer,
    RIG2_OT_FaceCapApplyNow,
    RIG2_OT_FaceCapClearKeys,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"Rig2 FaceCap register error for {cls.__name__}: {exc}")


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
