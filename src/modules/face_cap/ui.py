import bpy

from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from ...i18n import iface as _
from ..rig_controls.props import FRIENDLY_NAMES
from .runtime import get_runtime_service


def _format_packet_age(age_seconds):
    if age_seconds is None:
        return _("Waiting")
    if age_seconds < 1.0:
        return _f("{value:.0f} ms ago", value=age_seconds * 1000.0)
    return _f("{value:.2f} s ago", value=age_seconds)


def _format_transport_label(status):
    encoding = status.get("transport_encoding")
    if encoding == "binary":
        return _("WebSocket Binary")
    if encoding == "json":
        return _("WebSocket JSON")
    return _("WebSocket")


class FaceCapUIDrawer:
    INTERNAL_KEYS = {"_RNA_UI", "is_rig2"}

    @staticmethod
    def _draw_info_line(layout, label, value, *, icon="NONE"):
        text = _f("{label}: {value}", label=_(label), value=value)
        if icon == "NONE":
            layout.label(text=text)
        else:
            layout.label(text=text, icon=icon)

    @staticmethod
    def _draw_target_section(layout, obj, settings, status):
        layout.label(text=_("Target"), icon="ARMATURE_DATA")
        box = layout.box()
        if settings:
            box.prop(settings, "target_rig", text=_("Rig"))

        row = box.row(align=True)
        row.operator("rig2.face_cap_pin_current_rig", icon="PINNED")
        row.operator("rig2.face_cap_clear_target", icon="X")

        FaceCapUIDrawer._draw_info_line(box, "Current Context", obj.name)
        if status["target_name"]:
            FaceCapUIDrawer._draw_info_line(box, "Pinned Target", status["target_name"])
        else:
            box.label(text=_("Pinned Target: None"), icon="INFO")

    @staticmethod
    def _draw_receiver_section(layout, settings):
        layout.label(text=_("Receiver"), icon="URL")
        box = layout.box()
        if settings:
            box.prop(settings, "listen_host")
            box.prop(settings, "listen_port")

        row = box.row(align=True)
        row.operator("rig2.face_cap_start_server", icon="PLAY")
        row.operator("rig2.face_cap_stop_server", icon="PAUSE")

    @staticmethod
    def _draw_status_section(layout, status, enabled_rigs):
        box = layout.box()
        box.label(
            text=status["status_message"],
            icon="INFO" if not status["last_error"] else "ERROR",
        )
        FaceCapUIDrawer._draw_info_line(box, "Enabled rigs", enabled_rigs, icon="ARMATURE_DATA")
        FaceCapUIDrawer._draw_info_line(box, "Packets", status["packet_count"])
        FaceCapUIDrawer._draw_info_line(box, "Dropped", status["dropped_packet_count"])
        FaceCapUIDrawer._draw_info_line(box, "Applied", status["applied_packet_count"])
        FaceCapUIDrawer._draw_info_line(box, "Faces", status["face_count"], icon="USER")
        FaceCapUIDrawer._draw_info_line(
            box,
            "Transport",
            _format_transport_label(status),
            icon="URL",
        )
        FaceCapUIDrawer._draw_info_line(
            box,
            "Last packet",
            _format_packet_age(status["last_packet_age"]),
            icon="TIME",
        )
        if status["client_address"]:
            FaceCapUIDrawer._draw_info_line(box, "Client", status["client_address"])
        if status["last_error"]:
            box.label(text=status["last_error"], icon="ERROR")
        if not status["target_name"]:
            box.label(text=_("No pinned target rig selected."), icon="ERROR")
        if status["packet_count"] > 0 and enabled_rigs <= 0:
            box.label(text=_("No enabled rig. Set Face Capture to 1.00 on logic."), icon="ERROR")

    @staticmethod
    def _draw_data_section(layout, face_bone):
        layout.label(text=_("Data"), icon="ANIM_DATA")
        row = layout.row(align=True)
        row.enabled = bool(face_bone)
        row.operator("rig2.face_cap_apply_now", icon="IMPORT")
        row.operator("rig2.face_cap_clear_keys", icon="TRASH")

        if face_bone:
            mapped_count = len([key for key in face_bone.keys() if key not in FaceCapUIDrawer.INTERNAL_KEYS])
            layout.label(
                text=_f("{label}: {count}", label=_("Mapped Blendshapes"), count=mapped_count),
                icon="SHAPEKEY_DATA",
            )

    @staticmethod
    def draw(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        logic_bone = pose_bones.get("logic")
        face_bone = pose_bones.get("Face_BlendShapes")
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        service = get_runtime_service()
        status = service.get_status_snapshot()
        enabled_rigs = service.count_enabled_rigs()

        if logic_bone and "face_cap" in logic_bone:
            layout.label(text=_("Rig Switch"), icon="OUTLINER_OB_ARMATURE")
            layout.prop(
                logic_bone,
                '["face_cap"]',
                text=_(FRIENDLY_NAMES.get("face_cap", "Face Capture")),
                slider=True,
            )
            layout.separator()

        FaceCapUIDrawer._draw_target_section(layout, obj, settings, status)
        layout.separator()
        FaceCapUIDrawer._draw_receiver_section(layout, settings)
        FaceCapUIDrawer._draw_status_section(layout, status, enabled_rigs)
        layout.separator()
        FaceCapUIDrawer._draw_data_section(layout, face_bone)


class RIG2_PT_FaceCapPanel(bpy.types.Panel):
    bl_label = "Face Capture"
    bl_idname = "RIG2_PT_face_cap_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 25

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))

    def draw(self, context):
        FaceCapUIDrawer.draw(self.layout, context)


classes = (RIG2_PT_FaceCapPanel,)


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
