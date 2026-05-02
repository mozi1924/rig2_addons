import bpy

from ...core.constants import INTERNAL_KEYS
from ...core.registration import register_classes, unregister_classes
from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from ...i18n import iface as _
from ...licensing.ui_gate import draw_license_warnings
from ...services.face_cap_service import get_face_cap_backend_service
from ...ui.base import RIG2_PT_PanelBase
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
    @staticmethod
    def _draw_license_warnings(layout):
        return draw_license_warnings(layout)

    @staticmethod
    def _draw_backend_lock_hint(layout):
        FaceCapUIDrawer._draw_license_warnings(layout)
        backend_service = get_face_cap_backend_service()
        status = backend_service.get_feature_status()
        if backend_service.is_feature_unlocked():
            return False

        layout.label(text=_("Face Capture is unavailable"), icon="LOCKED")
        layout.label(text=status.get("message", backend_service.get_lock_reason()), icon="INFO")
        return True

    @staticmethod
    def _draw_info_line(layout, label, value, *, icon="NONE"):
        text = _f("{label}: {value}", label=_(label), value=value)
        if icon == "NONE":
            layout.label(text=text)
        else:
            layout.label(text=text, icon=icon)

    @staticmethod
    def _is_face_cap_enabled(item):
        rig = getattr(item, "rig", None)
        pose = getattr(rig, "pose", None) if rig else None
        logic_bone = pose.bones.get("logic") if pose else None
        if not logic_bone or "face_cap" not in logic_bone:
            return False

        try:
            return float(logic_bone.get("face_cap", 0.0)) >= 0.999
        except Exception:
            return False

    @staticmethod
    def _draw_binding_row(layout, item, binding_index, binding_status):
        is_missing = bool(binding_status and binding_status.get("missing"))
        is_enabled = FaceCapUIDrawer._is_face_cap_enabled(item)

        state_icon = "ERROR" if is_missing else ("CHECKMARK" if is_enabled else "PAUSE")
        row = layout.row(align=True)
        row.label(text="", icon=state_icon)

        # Rig selection
        row.prop(item, "rig", text="", icon="OBJECT_DATA")

        # Face index
        index_sub = row.row(align=True)
        index_sub.scale_x = 0.5
        index_sub.prop(item, "face_index", text="")

        # Remove button
        remove_op = row.operator("rig2.face_cap_remove_binding", text="", icon="X")
        remove_op.binding_index = binding_index

    @staticmethod
    def draw_header(layout, context):
        obj = get_context_object(context)
        if not obj:
            return

        pose_bones = obj.pose.bones
        logic_bone = pose_bones.get("logic")
        if not logic_bone:
            return

        if "face_cap" in logic_bone:
            layout.prop(
                logic_bone,
                '["face_cap"]',
                text=_(FRIENDLY_NAMES.get("face_cap", "Face Capture")),
                slider=True,
            )

        if "face_cap_hr" in logic_bone:
            layout.prop(
                logic_bone,
                '["face_cap_hr"]',
                text=_(FRIENDLY_NAMES.get("face_cap_hr", "Face Capture Head Rotation")),
                slider=True,
            )

    @staticmethod
    def draw_import_section(layout, context):
        is_locked = FaceCapUIDrawer._draw_backend_lock_hint(layout)
        row = layout.row()
        row.enabled = not is_locked
        row.operator("rig2.face_cap_import_json", text=_("Import Face Capture JSON"), icon="IMPORT")
        layout.label(
            text=_("Import starts at the current scene frame and follows the binding list"),
            icon="INFO",
        )

    @staticmethod
    def draw_bindings_section(layout, context):
        obj = get_context_object(context)
        scene = context.scene
        status = get_runtime_service().get_status_snapshot()

        if obj:
            FaceCapUIDrawer._draw_info_line(layout, "Current Context", obj.name)

        ensure_face_cap_binding_items(scene)
        items = getattr(scene, "rig2_face_cap_binding_items", None)
        if not items or len(items) == 0:
            layout.label(text=_("Face Binding List: Empty"), icon="INFO")
            footer = layout.row(align=True)
            footer.operator("rig2.face_cap_add_binding", text=_("New"), icon="ADD")
            return

        bindings = status.get("bindings", [])
        total_count = len(items)
        enabled_count = sum(1 for item in items if FaceCapUIDrawer._is_face_cap_enabled(item))
        missing_count = sum(
            1
            for binding_index in range(total_count)
            if binding_index < len(bindings) and bindings[binding_index].get("missing")
        )

        summary = layout.row(align=True)
        summary.label(text=_f("{label}: {value}", label=_("Bindings"), value=total_count), icon="LINKED")
        summary.label(text=_f("{label}: {value}", label=_("Enabled rigs"), value=enabled_count), icon="CHECKMARK")
        if missing_count > 0:
            summary.label(text=_f("{label}: {value}", label=_("Missing"), value=missing_count), icon="ERROR")

        list_box = layout.column(align=True)
        for binding_index, item in enumerate(items):
            binding_status = bindings[binding_index] if binding_index < len(bindings) else None
            FaceCapUIDrawer._draw_binding_row(list_box, item, binding_index, binding_status)

        footer = layout.row(align=True)
        footer.operator("rig2.face_cap_add_binding", text=_("New"), icon="ADD")

    @staticmethod
    def draw_receiver_section(layout, context):
        is_locked = FaceCapUIDrawer._draw_backend_lock_hint(layout)
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings:
            layout.prop(settings, "listen_host")
            layout.prop(settings, "listen_port")

        row = layout.row(align=True)
        row.enabled = not is_locked
        row.operator("rig2.face_cap_start_server", icon="PLAY")
        row.operator("rig2.face_cap_stop_server", icon="PAUSE")

    @staticmethod
    def draw_status_section(layout):
        backend_service = get_face_cap_backend_service()
        service = get_runtime_service()
        status = service.get_status_snapshot()
        enabled_rigs = service.count_enabled_rigs()

        layout.label(
            text=_("Face Capture backend unlocked")
            if backend_service.is_feature_unlocked()
            else _("Face Capture is unavailable"),
            icon="CHECKMARK" if backend_service.is_feature_unlocked() else "LOCKED",
        )
        if not backend_service.is_feature_unlocked():
            layout.label(text=backend_service.get_feature_status().get("message", ""), icon="INFO")
        layout.label(
            text=status["status_message"],
            icon="INFO" if not status["last_error"] else "ERROR",
        )
        if status["local_ipv4_address"]:
            FaceCapUIDrawer._draw_info_line(layout, "LAN IPv4", status["local_ipv4_address"], icon="URL")
        FaceCapUIDrawer._draw_info_line(layout, "Enabled rigs", enabled_rigs, icon="ARMATURE_DATA")
        FaceCapUIDrawer._draw_info_line(layout, "Packets", status["packet_count"])
        FaceCapUIDrawer._draw_info_line(layout, "Dropped", status["dropped_packet_count"])
        FaceCapUIDrawer._draw_info_line(layout, "Applied", status["applied_packet_count"])
        FaceCapUIDrawer._draw_info_line(layout, "Faces", status["face_count"], icon="USER")
        FaceCapUIDrawer._draw_info_line(
            layout,
            "Transport",
            _format_transport_label(status),
            icon="URL",
        )
        FaceCapUIDrawer._draw_info_line(
            layout,
            "Last packet",
            _format_packet_age(status["last_packet_age"]),
            icon="TIME",
        )
        if status["client_address"]:
            FaceCapUIDrawer._draw_info_line(layout, "Client", status["client_address"])
        if status["last_error"]:
            layout.label(text=status["last_error"], icon="ERROR")
        if not status.get("bindings"):
            layout.label(text=_("No face binding configured."), icon="ERROR")
        if status["packet_count"] > 0 and enabled_rigs <= 0:
            layout.label(text=_("No enabled rig in bindings. Set Face Capture to 1.00 on logic."), icon="ERROR")

    @staticmethod
    def draw_data_section(layout, context):
        is_locked = FaceCapUIDrawer._draw_backend_lock_hint(layout)
        obj = get_context_object(context)
        face_bone = obj.pose.bones.get("Face_BlendShapes") if obj else None

        row = layout.row(align=True)
        row.enabled = bool(face_bone) and not is_locked
        row.operator("rig2.face_cap_apply_now", icon="IMPORT")
        row.operator("rig2.face_cap_clear_keys", icon="TRASH")

        if face_bone:
            mapped_count = len([key for key in face_bone.keys() if key not in INTERNAL_KEYS])
            layout.label(
                text=_f("{label}: {count}", label=_("Mapped Blendshapes"), count=mapped_count),
                icon="SHAPEKEY_DATA",
            )


class RIG2_PT_FaceCapPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Face Capture"
    bl_idname = "RIG2_PT_face_cap_panel"
    bl_order = 25

    def draw(self, context):
        FaceCapUIDrawer.draw_header(self.layout, context)


class RIG2_PT_FaceCapImportPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Import"
    bl_idname = "RIG2_PT_face_cap_import_panel"
    bl_parent_id = "RIG2_PT_face_cap_panel"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 20

    def draw(self, context):
        FaceCapUIDrawer.draw_import_section(self.layout, context)


class RIG2_PT_FaceCapReceiverPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Receiver"
    bl_idname = "RIG2_PT_face_cap_receiver_panel"
    bl_parent_id = "RIG2_PT_face_cap_panel"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 30

    def draw(self, context):
        FaceCapUIDrawer.draw_receiver_section(self.layout, context)


class RIG2_PT_FaceCapBindingsPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Bindings"
    bl_idname = "RIG2_PT_face_cap_bindings_panel"
    bl_parent_id = "RIG2_PT_face_cap_panel"
    bl_order = 10

    def draw(self, context):
        FaceCapUIDrawer.draw_bindings_section(self.layout, context)


class RIG2_PT_FaceCapStatusPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Status"
    bl_idname = "RIG2_PT_face_cap_status_panel"
    bl_parent_id = "RIG2_PT_face_cap_panel"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 40

    def draw(self, context):
        FaceCapUIDrawer.draw_status_section(self.layout)


class RIG2_PT_FaceCapDataPanel(RIG2_PT_PanelBase, bpy.types.Panel):
    bl_label = "Data"
    bl_idname = "RIG2_PT_face_cap_data_panel"
    bl_parent_id = "RIG2_PT_face_cap_panel"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 50

    def draw(self, context):
        FaceCapUIDrawer.draw_data_section(self.layout, context)


classes = (
    RIG2_PT_FaceCapPanel,
    RIG2_PT_FaceCapImportPanel,
    RIG2_PT_FaceCapReceiverPanel,
    RIG2_PT_FaceCapBindingsPanel,
    RIG2_PT_FaceCapStatusPanel,
    RIG2_PT_FaceCapDataPanel,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
