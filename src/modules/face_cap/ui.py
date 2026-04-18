import bpy

from ...core.utils import get_context_object, is_rig2_armature
from ..rig_controls.props import FRIENDLY_NAMES
from .runtime import get_runtime_service


def _format_packet_age(age_seconds):
    if age_seconds is None:
        return "Waiting"
    if age_seconds < 1.0:
        return f"{age_seconds * 1000.0:.0f} ms ago"
    return f"{age_seconds:.2f} s ago"


class RIG2_PT_FaceCapPanel(bpy.types.Panel):
    bl_label = "Face Capture"
    bl_idname = "RIG2_PT_face_cap_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 25
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))

    def draw(self, context):
        layout = self.layout
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        head_bone = pose_bones.get("prop.head")
        face_bone = pose_bones.get("Face_BlendShapes")
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        service = get_runtime_service()
        status = service.get_status_snapshot()
        enabled_rigs = service.count_enabled_rigs()

        if head_bone and "face_cap" in head_bone:
            layout.label(text="Rig Switch", icon="OUTLINER_OB_ARMATURE")
            layout.prop(
                head_bone,
                '["face_cap"]',
                text=FRIENDLY_NAMES.get("face_cap", "Face Capture"),
                slider=True,
            )

        layout.separator()
        layout.label(text="Receiver", icon="URL")
        box = layout.box()
        col = box.column(align=True)
        if settings:
            col.prop(settings, "listen_host")
            col.prop(settings, "listen_port")
        col.operator("rig2.face_cap_restart_server", icon="FILE_REFRESH")

        info = layout.box()
        info.label(text=status["status_message"], icon="INFO" if not status["last_error"] else "ERROR")
        info.label(text=f"Enabled rigs: {enabled_rigs}", icon="ARMATURE_DATA")
        info.label(text=f"Packets: {status['packet_count']}")
        info.label(text=f"Faces: {status['face_count']}", icon="USER")
        info.label(text=f"Last packet: {_format_packet_age(status['last_packet_age'])}", icon="TIME")
        if status["client_address"]:
            info.label(text=f"Client: {status['client_address']}")
        if status["last_error"]:
            info.label(text=status["last_error"], icon="ERROR")
        if status["packet_count"] > 0 and enabled_rigs <= 0:
            info.label(text="No enabled rig. Set Face Capture to 1.00 on prop.head.", icon="ERROR")

        layout.separator()
        layout.label(text="Data", icon="ANIM_DATA")
        row = layout.row(align=True)
        row.enabled = bool(face_bone)
        row.operator("rig2.face_cap_apply_now", icon="IMPORT")
        row.operator("rig2.face_cap_clear_keys", icon="TRASH")

        if face_bone:
            layout.label(text=f"Mapped Blendshapes: {len([k for k in face_bone.keys() if k not in {'_RNA_UI', 'is_rig2'}])}", icon="SHAPEKEY_DATA")


class RIG2_PT_SideFaceCapPanel(bpy.types.Panel):
    bl_label = "Face Capture"
    bl_idname = "RIG2_PT_side_face_cap_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rig/2"
    bl_parent_id = "RIG2_PT_side_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if not obj or not obj.pose:
            return

        pose_bones = obj.pose.bones
        head_bone = pose_bones.get("prop.head")
        face_bone = pose_bones.get("Face_BlendShapes")
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        service = get_runtime_service()
        status = service.get_status_snapshot()
        enabled_rigs = service.count_enabled_rigs()

        if head_bone and "face_cap" in head_bone:
            layout.prop(
                head_bone,
                '["face_cap"]',
                text=FRIENDLY_NAMES.get("face_cap", "Face Capture"),
                slider=True,
            )

        col = layout.column(align=True)
        if settings:
            col.prop(settings, "listen_host", text="Host")
            col.prop(settings, "listen_port", text="Port")
        col.operator("rig2.face_cap_restart_server", icon="FILE_REFRESH")

        box = layout.box()
        box.label(text=status["status_message"], icon="INFO" if not status["last_error"] else "ERROR")
        box.label(text=f"Packets: {status['packet_count']}")
        box.label(text=f"Faces: {status['face_count']}")
        box.label(text=f"Enabled rigs: {enabled_rigs}")
        if status["client_address"]:
            box.label(text=f"Client: {status['client_address']}")
        if status["packet_count"] > 0 and enabled_rigs <= 0:
            box.label(text="Set Face Capture to 1.00 first.", icon="ERROR")

        row = layout.row(align=True)
        row.enabled = bool(face_bone)
        row.operator("rig2.face_cap_apply_now", icon="IMPORT")
        row.operator("rig2.face_cap_clear_keys", icon="TRASH")


classes = (
    RIG2_PT_FaceCapPanel,
    RIG2_PT_SideFaceCapPanel,
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
