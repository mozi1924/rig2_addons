import bpy

from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from .props import (
    ensure_face_cap_binding_items,
    get_face_cap_bindings,
    set_face_cap_bindings,
    sync_face_cap_bindings_to_scene_prop,
)
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


class RIG2_OT_FaceCapAddBinding(bpy.types.Operator):
    bl_idname = "rig2.face_cap_add_binding"
    bl_label = "New"
    bl_description = "Add a new face capture binding row"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        ensure_face_cap_binding_items(context.scene)
        items = getattr(context.scene, "rig2_face_cap_binding_items", None)
        if items is None:
            self.report({"ERROR"}, _f("Face Capture binding list is not registered"))
            return {"CANCELLED"}

        item = items.add()
        obj = get_context_object(context)
        if is_rig2_armature(obj):
            item.rig = obj
        item.face_index = 0
        sync_face_cap_bindings_to_scene_prop(context.scene)
        get_runtime_service().request_reapply()
        self.report({"INFO"}, _f("Added new face binding row"))
        return {"FINISHED"}


class RIG2_OT_FaceCapRemoveBinding(bpy.types.Operator):
    bl_idname = "rig2.face_cap_remove_binding"
    bl_label = "Remove Face Binding"
    bl_description = "Remove a face capture binding from the scene list"

    binding_index: bpy.props.IntProperty(default=-1, min=-1)

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        ensure_face_cap_binding_items(context.scene)
        items = getattr(context.scene, "rig2_face_cap_binding_items", None)
        if items is None:
            self.report({"ERROR"}, _f("Face Capture binding list is not registered"))
            return {"CANCELLED"}

        if self.binding_index < 0 or self.binding_index >= len(items):
            self.report({"ERROR"}, _f("Face binding index is out of range"))
            return {"CANCELLED"}

        removed = items[self.binding_index]
        removed_name = removed.rig.name if getattr(removed, "rig", None) else ""
        removed_face_index = int(getattr(removed, "face_index", 0))
        items.remove(self.binding_index)
        sync_face_cap_bindings_to_scene_prop(context.scene)
        get_runtime_service().request_reapply()
        self.report(
            {"INFO"},
            _f(
                "Removed face binding: Face {face_index} -> {name}",
                face_index=removed_face_index,
                name=removed_name,
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapClearBindings(bpy.types.Operator):
    bl_idname = "rig2.face_cap_clear_bindings"
    bl_label = "Clear Face Bindings"
    bl_description = "Clear every face capture binding stored on this scene"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        set_face_cap_bindings(context.scene, [])
        get_runtime_service().request_reapply()
        self.report({"INFO"}, _f("Face Capture bindings cleared"))
        return {"FINISHED"}


class RIG2_OT_FaceCapStartServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_start_server"
    bl_label = "Start Face Capture Receiver"
    bl_description = "Start the local face capture WebSocket receiver"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        service = get_runtime_service()
        service.start(settings=settings)
        binding_count = len(get_face_cap_bindings(context.scene))
        status = service.get_status_snapshot()
        local_ipv4_address = status.get("local_ipv4_address", "")
        receiver_host = local_ipv4_address or settings.listen_host
        self.report(
            {"INFO"},
            _f(
                "Face Capture receiver started on ws://{host}:{port} with {count} binding(s)",
                host=receiver_host,
                port=settings.listen_port,
                count=binding_count,
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapStopServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_stop_server"
    bl_label = "Stop Face Capture Receiver"
    bl_description = "Stop the local face capture WebSocket receiver"

    def execute(self, context):
        service = get_runtime_service()
        service.stop()
        self.report({"INFO"}, _f("Face Capture receiver stopped"))
        return {"FINISHED"}


class RIG2_OT_FaceCapApplyNow(bpy.types.Operator):
    bl_idname = "rig2.face_cap_apply_now"
    bl_label = "Apply Cached Face Packet"
    bl_description = "Apply the latest received blendshape packet to enabled Rig2 armatures immediately"

    def execute(self, context):
        service = get_runtime_service()
        service.apply_latest_data()
        self.report(
            {"INFO"},
            _f(
                "Applied cached face packet to {count} enabled rig(s)",
                count=service.count_enabled_rigs(),
            ),
        )
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
            self.report({"ERROR"}, _f("Face_BlendShapes bone not found"))
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

        self.report(
            {"INFO"},
            _f(
                "Cleared {curve_count} face capture f-curves and reset {blendshape_count} blendshape values",
                curve_count=removed_curves,
                blendshape_count=len(prop_names),
            ),
        )
        return {"FINISHED"}


classes = (
    RIG2_OT_FaceCapAddBinding,
    RIG2_OT_FaceCapRemoveBinding,
    RIG2_OT_FaceCapClearBindings,
    RIG2_OT_FaceCapStartServer,
    RIG2_OT_FaceCapStopServer,
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
