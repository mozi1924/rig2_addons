import bpy

from .core.utils import tag_context_redraw
from .i18n import iface as _
from .licensing.config import FEATURE_FACE_CAP, FEATURE_MIFRAMES, FEATURE_R2BB
from .services.registry import get_feature_service
from .licensing.ui_helpers import (
    format_expiry_label,
    format_heartbeat_label,
    format_timestamp_local,
)


_SAFE_STATUS_ICONS = {"ERROR", "INFO", "CHECKMARK", "TIME", "LOCKED", "UNLOCKED"}


def _safe_status_icon(icon_name: str, fallback: str = "INFO") -> str:
    """Return a Blender-safe icon name for UI labels."""
    if icon_name in _SAFE_STATUS_ICONS:
        return icon_name
    return fallback if fallback in _SAFE_STATUS_ICONS else "INFO"


class Rig2AddonPreferences(bpy.types.AddonPreferences):
    # Get the root package name robustly
    bl_idname = __package__.partition('.')[0] if __package__ else "rig2_addons"

    show_n_panel: bpy.props.BoolProperty(
        name="Show N-Panel",
        description="Show the Rig2 control panel in the 3D View side panel (N-key)",
        default=True,
    )

    show_logic_props: bpy.props.BoolProperty(
        name="Show all logic properties",
        description="Show all custom properties for the 'logic' bone in the Danger Zone",
        default=False,
    )

    license_key: bpy.props.StringProperty(
        name="License Key",
        description="Orbisauth license key for activating commercial features",
        default="",
        subtype="PASSWORD",
    )

    def draw(self, context):
        layout = self.layout

        # -- License section --
        box = layout.box()
        box.label(text="License", icon="KEYINGSET")
        status = _get_license_status()
        has_session = _has_license_session()

        if has_session:
            box.label(text=f"Product: {status['product']}", icon="CHECKMARK")
            box.label(text=f"Tier: {status['tier']}")
            if status.get("license_id"):
                box.label(text=f"License: {status['license_id']}")
            if status.get("device_id"):
                box.label(text=f"Device: {status['device_id']}")

            state_row = box.row()
            if status.get("is_refresh_expired"):
                state_row.alert = True
                state_row.label(text="Session: Expired", icon="ERROR")
            elif status.get("warnings"):
                state_row.label(text="Session: Needs Attention", icon="INFO")
            elif status.get("activated"):
                state_row.label(text="Session: Active", icon="CHECKMARK")
            else:
                state_row.label(text="Session: Recoverable", icon="INFO")

            offline_remaining = status.get("offline_valid_remaining_seconds", 0)
            offline_until = status.get("offline_valid_until", 0)
            session_remaining = status.get("session_valid_remaining_seconds", 0)
            session_until = status.get("session_valid_until", 0)

            offline_icon = "TIME" if offline_remaining > 0 else "ERROR"
            box.label(
                text=f"Offline License: {format_expiry_label(offline_remaining)}",
                icon=offline_icon,
            )
            box.label(
                text=f"Valid until: {format_timestamp_local(offline_until)}",
                icon="TIME",
            )

            renewal_label = (
                format_expiry_label(
                    session_remaining,
                    expired_label="Re-activation required",
                )
                if not status.get("is_refresh_expired")
                else "Re-activation required"
            )
            renewal_icon = "TIME" if session_remaining > 0 else "ERROR"
            box.label(text=f"Session Renewal: {renewal_label}", icon=renewal_icon)
            box.label(
                text=f"Renewal until: {format_timestamp_local(session_until)}",
                icon="TIME",
            )

            # Heartbeat status
            heartbeat_label = format_heartbeat_label(status)
            heartbeat_icon = "TIME" if status.get("heartbeat_in_flight") else "INFO"
            if heartbeat_label == "healthy":
                heartbeat_icon = "CHECKMARK"
            elif "failed" in heartbeat_label or heartbeat_label == "pending":
                heartbeat_icon = "INFO"
            elif "overdue" in heartbeat_label:
                heartbeat_icon = "ERROR"
            box.label(text=f"Heartbeat: {heartbeat_label}", icon=heartbeat_icon)
            box.label(
                text=f"Last success: {format_timestamp_local(status.get('last_heartbeat_at', 0))}",
                icon="TIME",
            )
            box.label(
                text=f"Last attempt: {format_timestamp_local(status.get('last_heartbeat_attempt_at', 0))}",
                icon="TIME",
            )

            # Warnings
            for w in status.get("warnings", []):
                row = box.row()
                row.alert = True
                level = str(w.get("level", "")).upper()
                if level in {"ERROR", "CRITICAL"}:
                    icon = "ERROR"
                elif level in {"WARNING", "WARN"}:
                    # Blender icon sets vary; use safe icons only.
                    icon = "INFO"
                else:
                    icon = "INFO"
                row.label(text=w.get("message", "Unknown warning"), icon=_safe_status_icon(icon))

            licensed_features = [
                f for f, v in status.get("features", {}).items() if v
            ]
            if licensed_features:
                box.label(
                    text=f"Features: {', '.join(licensed_features)}",
                    icon="UNLOCKED",
                )
            else:
                box.label(text="No features licensed", icon="LOCKED")
            action_row = box.row(align=True)
            sync_row = action_row.row(align=True)
            sync_row.enabled = not bool(status.get("is_refresh_expired"))
            sync_row.operator(
                RIG2_OT_sync_license_status.bl_idname,
                text="Sync Now",
                icon="FILE_REFRESH",
            )
            action_row.operator(
                RIG2_OT_deactivate_license.bl_idname,
                text="Deactivate",
                icon="UNLINKED",
            )
            if status.get("is_refresh_expired"):
                hint_row = box.row()
                hint_row.label(
                    text="Sync is unavailable for an expired session. Re-activate your license.",
                    icon="INFO",
                )
        else:
            box.label(text="Not activated", icon="LOCKED")
            col = box.column()
            col.prop(self, "license_key")
            col.operator(
                RIG2_OT_activate_license.bl_idname,
                text="Activate",
                icon="PLAY",
            )

        entitled_features = [
            feature_name
            for feature_name in (FEATURE_FACE_CAP, FEATURE_MIFRAMES, FEATURE_R2BB)
            if has_session and bool(status.get("features", {}).get(feature_name, False))
        ]

        if entitled_features:
            feature_box = layout.box()
            feature_box.label(text="Feature Access", icon="FILE_CACHE")
            for feature_name in entitled_features:
                _draw_feature_status(feature_box, feature_name)

        settings_box = layout.box()
        settings_box.label(text="Settings", icon="PREFERENCES")
        column = settings_box.column()
        column.prop(self, "show_n_panel")
        column.prop(self, "show_logic_props")


# Simple local rate limiter for activation attempts.
_activate_attempts: list[float] = []
_ACTIVATE_MAX_ATTEMPTS = 3
_ACTIVATE_WINDOW_SECONDS = 60


class RIG2_OT_activate_license(bpy.types.Operator):
    bl_idname = "rig2.activate_license"
    bl_label = "Activate License"
    bl_description = "Activate a Rig2 license key via Orbisauth"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        import time
        global _activate_attempts
        now = time.time()
        _activate_attempts = [t for t in _activate_attempts if now - t < _ACTIVATE_WINDOW_SECONDS]
        if len(_activate_attempts) >= _ACTIVATE_MAX_ATTEMPTS:
            self.report(
                {"ERROR"},
                f"Too many activation attempts. Please wait {_ACTIVATE_WINDOW_SECONDS} seconds.",
            )
            return {"CANCELLED"}
        _activate_attempts.append(now)

        prefs = get_preferences()
        if not prefs or not prefs.license_key.strip():
            self.report({"ERROR"}, "Please enter a license key.")
            return {"CANCELLED"}

        import traceback
        try:
            from .licensing.feature_access import activate_and_prepare_features

            result = activate_and_prepare_features(prefs.license_key.strip())
            session = result["session"]
            labels = result.get("download_labels", {})
            failed = [
                labels.get(feature_name, feature_name)
                for feature_name, item in result["download_results"].items()
                if not item.get("ok")
            ]
            if failed:
                self.report(
                    {"WARNING"},
                    (
                        f"License activated: {session.product} ({session.tier}). "
                        f"Some binaries still need attention: {', '.join(failed)}."
                    ),
                )
            else:
                self.report(
                    {"INFO"},
                    f"License activated: {session.product} ({session.tier})",
                )
        except Exception as exc:
            # Build a detailed error message including HTTP status / error code.
            status_code = getattr(exc, "status_code", None)
            error_code = getattr(exc, "error_code", None)
            if status_code is not None and error_code is not None:
                detail = f"Activation failed [{error_code}]: {exc} (HTTP {status_code})"
            else:
                detail = f"Activation failed: {exc}"
            self.report({"ERROR"}, detail)
            traceback.print_exc()
            return {"CANCELLED"}

        # Redraw all areas so the preferences UI reflects the new state.
        _refresh_ui()
        return {"FINISHED"}


class RIG2_OT_deactivate_license(bpy.types.Operator):
    bl_idname = "rig2.deactivate_license"
    bl_label = "Deactivate License"
    bl_description = "Remove the current license activation"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        from .licensing.manager import get_license_manager
        from .licensing.feature_access import clear_feature_state, refresh_feature_runtime

        manager = get_license_manager()
        manager.deactivate()
        clear_feature_state()
        refresh_feature_runtime()
        self.report({"INFO"}, "License deactivated.")
        _refresh_ui()
        return {"FINISHED"}


class RIG2_OT_sync_license_status(bpy.types.Operator):
    bl_idname = "rig2.sync_license_status"
    bl_label = "Sync License Status"
    bl_description = "Immediately sync license status with the server and refresh local feature access"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        try:
            from .licensing.manager import get_license_manager

            manager = get_license_manager()
            if getattr(getattr(manager, "_client", None), "session", None) is None:
                self.report({"ERROR"}, "No active license session to sync.")
                return {"CANCELLED"}

            started = manager.request_heartbeat(
                reason="manual_sync",
                force=True,
                refresh_runtime=True,
            )
            if started:
                self.report({"INFO"}, "License sync started in background.")
            else:
                if manager.is_heartbeat_in_flight():
                    self.report({"INFO"}, "License sync is already running in background.")
                else:
                    self.report({"WARNING"}, "License sync is not available right now.")
        except Exception as exc:
            import traceback

            status_code = getattr(exc, "status_code", None)
            error_code = getattr(exc, "error_code", None)
            if status_code is not None and error_code is not None:
                detail = f"Sync failed [{error_code}]: {exc} (HTTP {status_code})"
            else:
                detail = f"Sync failed: {exc}"
            self.report({"ERROR"}, detail)
            traceback.print_exc()
            return {"CANCELLED"}

        _refresh_ui()
        return {"FINISHED"}


def _get_license_status():
    """Return license status dict safe for use during draw()."""
    try:
        from .licensing import process_pending_native_sync
        from .licensing.manager import get_license_manager
        manager = get_license_manager()
        status = manager.get_status()

        try:
            process_pending_native_sync()
        except Exception:
            pass

        return status
    except Exception:
        return {
            "activated": False,
            "product": "",
            "tier": "",
            "license_id": "",
            "device_name": "",
            "features": {},
        }


def _has_license_session():
    try:
        from .licensing.manager import get_license_manager

        manager = get_license_manager()
        return getattr(getattr(manager, "_client", None), "session", None) is not None
    except Exception:
        return False


def _get_feature_status(feature_name):
    try:
        return get_feature_service(feature_name).get_feature_status()
    except Exception:
        from .licensing.feature_access import get_feature_status
        try:
            return get_feature_status(feature_name, probe_native=True)
        except TypeError:
            # Backward-compatible for tests or legacy shims.
            return get_feature_status(feature_name)


def _draw_feature_status(box, feature_name):
    status = _get_feature_status(feature_name)
    row = box.row()
    state_label = _feature_label(status["effective_state"])
    row.label(
        text=f"{status['label']}: {state_label}",
        icon=_feature_icon(status["effective_state"]),
    )

    message_text = status["message"]
    if status["effective_state"] == "needs_restart":
        message_text = _("Binary updated. Restart Blender to enable this feature.")

    message_row = box.row()
    message_row.scale_y = 0.9
    message_row.label(text=message_text, icon="INFO")

    if status.get("load_error") and status["effective_state"] == "needs_redownload":
        error_row = box.row()
        error_row.alert = True
        error_row.label(text=status["load_error"], icon="ERROR")

    if status.get("native_reason") and status["effective_state"] == "needs_redownload":
        error_row = box.row()
        error_row.alert = True
        error_row.label(text=status["native_reason"], icon="ERROR")

    if status.get("residual_module_paths") and status["effective_state"] == "needs_redownload":
        for residual_path in status["residual_module_paths"]:
            residual_row = box.row()
            residual_row.alert = True
            residual_row.label(text=residual_path, icon="FILE")

    if status["can_download"]:
        action_row = box.row()
        action_row.operator(
            RIG2_OT_download_native.bl_idname,
            text=_("Retry Download") if status["can_retry"] else _("Download Binary"),
            icon="IMPORT",
        ).feature_name = feature_name


def _feature_icon(effective_state):
    if effective_state == "ready":
        return "CHECKMARK"
    if effective_state == "session_warning":
        return "INFO"
    if effective_state in {
        "download_failed",
        "binary_missing",
        "needs_redownload",
        "needs_restart",
        "session_error",
    }:
        return "ERROR"
    return "LOCKED"


def _feature_label(effective_state):
    if effective_state in {"binary_missing", "download_failed", "needs_redownload"}:
        return _("Disabled")
    if effective_state == "needs_restart":
        return _("Restart Required")
    if effective_state == "session_warning":
        return _("Needs Attention")
    return effective_state.replace("_", " ").title()


class RIG2_OT_download_native(bpy.types.Operator):
    bl_idname = "rig2.download_native"
    bl_label = "Download Native Binary"
    bl_description = "Download a native binary via your license"
    bl_options = {"REGISTER", "INTERNAL"}

    feature_name: bpy.props.StringProperty()

    def execute(self, context):
        try:
            from .licensing.feature_access import download_feature_binary, get_feature_status

            result = download_feature_binary(self.feature_name, force=True)
            status = get_feature_status(self.feature_name)
            if result["ok"]:
                self.report(
                    {"INFO"},
                    result.get("message") or f"{status['label']} binary is ready.",
                )
            else:
                self.report({"ERROR"}, result["error"] or status["message"])
        except Exception as exc:
            import traceback

            status_code = getattr(exc, "status_code", None)
            error_code = getattr(exc, "error_code", None)
            if status_code is not None and error_code is not None:
                detail = f"Download failed [{error_code}]: {exc} (HTTP {status_code})"
            else:
                detail = f"Download failed: {exc}"
            self.report({"ERROR"}, detail)
            traceback.print_exc()
            return {"CANCELLED"}

        _refresh_ui()
        return {"FINISHED"}


def _refresh_ui():
    """Tag all windows for redraw so the preferences panel updates."""
    tag_context_redraw()


def get_preferences():
    addon_name = __package__.partition('.')[0] if __package__ else "rig2_addons"
    addon = bpy.context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


from .core.registration import register_classes, unregister_classes

classes = (
    Rig2AddonPreferences,
    RIG2_OT_activate_license,
    RIG2_OT_deactivate_license,
    RIG2_OT_sync_license_status,
    RIG2_OT_download_native,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
