import bpy

from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from ...i18n import iface as _
from .props import ensure_face_cap_binding_items
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
    def _draw_target_section(layout, obj, scene, status):
        layout.label(text=_("Bindings"), icon="ARMATURE_DATA")
        box = layout.box()
        FaceCapUIDrawer._draw_info_line(box, "Current Context", obj.name)
        ensure_face_cap_binding_items(scene)
        items = getattr(scene, "rig2_face_cap_binding_items", None)
        if not items or len(items) == 0:
            box.label(text=_("Face Binding List: Empty"), icon="INFO")
        else:
            list_box = box.column(align=True)
            bindings = status.get("bindings", [])
            for binding_index, item in enumerate(items):
                row = list_box.row(align=True)
                fields = row.split(factor=0.76, align=True)
                rig_col = fields.row(align=True)
                rig_col.prop(item, "rig", text="", icon="OBJECT_DATA")

                right = fields.row(align=True)
                index_col = right.row(align=True)
                index_col.scale_x = 0.9
                index_col.prop(item, "face_index", text="")
                if binding_index < len(bindings) and bindings[binding_index].get("missing"):
                    right.label(text="", icon="ERROR")
                remove_op = right.operator("rig2.face_cap_remove_binding", text="", icon="X")
                remove_op.binding_index = binding_index

        footer = box.row(align=True)
        footer.operator("rig2.face_cap_add_binding", text=_("New"), icon="ADD")

    @staticmethod
    def _draw_receiver_section(layout, settings):
        layout.label(text=_("Receiver"), icon="URL")
        box = layout.box()
        if settings:
            box.prop(settings, "listen_host")
            box.prop(settings, "listen_port")
            box.prop(settings, "include_head_rotation")

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
        if status["local_ipv4_address"]:
            FaceCapUIDrawer._draw_info_line(box, "LAN IPv4", status["local_ipv4_address"], icon="URL")
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
        if not status.get("bindings"):
            box.label(text=_("No face binding configured."), icon="ERROR")
        if status["packet_count"] > 0 and enabled_rigs <= 0:
            box.label(text=_("No enabled rig in bindings. Set Face Capture to 1.00 on logic."), icon="ERROR")

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

        FaceCapUIDrawer._draw_target_section(layout, obj, context.scene, status)
        layout.separator()
        FaceCapUIDrawer._draw_receiver_section(
            layout,
            getattr(context.scene, "rig2_face_cap_settings", None),
        )
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
