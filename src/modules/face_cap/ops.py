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


class RIG2_OT_FaceCapPinCurrentRig(bpy.types.Operator):
    bl_idname = "rig2.face_cap_pin_current_rig"
    bl_label = "Pin Current Rig"
    bl_description = "Use the current Rig2 armature as the only face capture target"

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, "Face Capture settings are not registered")
            return {"CANCELLED"}

        obj = get_context_object(context)
        if not is_rig2_armature(obj):
            self.report({"ERROR"}, "Current object is not a Rig2 armature")
            return {"CANCELLED"}

        settings.target_rig = obj
        self.report({"INFO"}, f"Face Capture target pinned to {obj.name}")
        return {"FINISHED"}


class RIG2_OT_FaceCapClearTarget(bpy.types.Operator):
    bl_idname = "rig2.face_cap_clear_target"
    bl_label = "Clear Face Target"
    bl_description = "Clear the currently pinned face capture target rig"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, "Face Capture settings are not registered")
            return {"CANCELLED"}

        settings.target_rig = None
        self.report({"INFO"}, "Face Capture target cleared")
        return {"FINISHED"}


class RIG2_OT_FaceCapStartServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_start_server"
    bl_label = "Start Face Capture Receiver"
    bl_description = "Start the local WebSocket receiver and, when available, the integrated WebTransport server"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, "Face Capture settings are not registered")
            return {"CANCELLED"}

        obj = get_context_object(context)
        if is_rig2_armature(obj):
            settings.target_rig = obj

        service = get_runtime_service()
        service.start(settings=settings)
        status = service.get_status_snapshot()
        target_name = settings.target_rig.name if settings.target_rig else "No target"
        if service.is_webtransport_running():
            self.report(
                {"INFO"},
                f"Face Capture receiver started on ws://{settings.listen_host}:{settings.listen_port} with WebTransport {status['webtransport_status']} for {target_name}",
            )
        else:
            self.report({"INFO"}, f"Face Capture receiver started on ws://{settings.listen_host}:{settings.listen_port} for {target_name}")
        return {"FINISHED"}


class RIG2_OT_FaceCapStopServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_stop_server"
    bl_label = "Stop Face Capture Receiver"
    bl_description = "Stop the local face capture WebSocket receiver"

    def execute(self, context):
        service = get_runtime_service()
        service.stop()
        self.report({"INFO"}, "Face Capture receiver stopped")
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


class RIG2_OT_FaceCapInstallWebTransportDependency(bpy.types.Operator):
    bl_idname = "rig2.face_cap_install_webtransport_dependency"
    bl_label = "Install WT Dependency"
    bl_description = "Install the aioquic dependency used by the integrated WebTransport server"

    def execute(self, context):
        service = get_runtime_service()
        was_running = service.is_running()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "rig2_face_cap_settings", None) if scene else None
        try:
            dependency_dir = service.install_webtransport_dependency()
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to install WebTransport dependency: {exc}")
            return {"CANCELLED"}

        if was_running:
            service.start(settings=settings)

        self.report({"INFO"}, f"WebTransport dependency ready: {dependency_dir}")
        return {"FINISHED"}


class RIG2_OT_FaceCapUninstallWebTransportDependency(bpy.types.Operator):
    bl_idname = "rig2.face_cap_uninstall_webtransport_dependency"
    bl_label = "Uninstall WT Dependency"
    bl_description = "Remove the addon-managed aioquic dependency and fall back to WebSocket only"

    def execute(self, context):
        service = get_runtime_service()
        was_running = service.is_running()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "rig2_face_cap_settings", None) if scene else None
        service.stop()
        try:
            dependency_dir = service.uninstall_webtransport_dependency()
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to uninstall WebTransport dependency: {exc}")
            return {"CANCELLED"}

        if was_running:
            service.start(settings=settings)

        self.report({"INFO"}, f"Removed addon-managed WT dependency from {dependency_dir}")
        return {"FINISHED"}


classes = (
    RIG2_OT_FaceCapPinCurrentRig,
    RIG2_OT_FaceCapClearTarget,
    RIG2_OT_FaceCapStartServer,
    RIG2_OT_FaceCapStopServer,
    RIG2_OT_FaceCapApplyNow,
    RIG2_OT_FaceCapClearKeys,
    RIG2_OT_FaceCapInstallWebTransportDependency,
    RIG2_OT_FaceCapUninstallWebTransportDependency,
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
