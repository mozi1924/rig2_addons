import bpy


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

        if status["activated"]:
            box.label(text=f"Product: {status['product']}", icon="CHECKMARK")
            box.label(text=f"Tier: {status['tier']}")
            if status.get("license_id"):
                box.label(text=f"License: {status['license_id']}")
            if status.get("device_id"):
                box.label(text=f"Device: {status['device_id']}")

            # Token expiry info
            access_exp = status.get("access_token_expires_in_seconds", 0)
            if access_exp > 0:
                if status.get("is_access_expired"):
                    box.label(text="Access Token: EXPIRED", icon="ERROR")
                else:
                    hours = access_exp // 3600
                    mins = (access_exp % 3600) // 60
                    box.label(
                        text=f"Access Token: {hours}h {mins}m remaining",
                        icon="TIME",
                    )

            # Heartbeat status
            hb_failures = status.get("consecutive_heartbeat_failures", 0)
            last_hb = status.get("last_heartbeat_at", 0)
            if last_hb and hb_failures == 0:
                box.label(text="Heartbeat: OK", icon="CHECKMARK")
            elif hb_failures > 0:
                box.label(
                    text=f"Heartbeat: {hb_failures} failures",
                    icon="INFO",
                )
            else:
                box.label(text="Heartbeat: pending", icon="TIME")

            # Warnings
            for w in status.get("warnings", []):
                row = box.row()
                row.alert = True
                icon = "ERROR" if w["level"] == "ERROR" else "INFO"
                row.label(text=w["message"], icon=icon)

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
            deactivate_col = box.column()
            deactivate_col.operator(
                RIG2_OT_deactivate_license.bl_idname,
                text="Deactivate",
                icon="UNLINKED",
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

        # -- Native Binaries section --
        box = layout.box()
        box.label(text="Native Binaries", icon="FILE_CACHE")
        _draw_binary_status(box, "rig2_face_cap", "Face Capture")
        _draw_binary_status(box, "rig2_miframes", "MIFrames")

        box.separator()
        box.label(text="Settings", icon="PREFERENCES")
        column = box.column()
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

        from .licensing.manager import get_license_manager
        from .licensing import sync_license_to_native_modules

        import traceback
        manager = get_license_manager()
        try:
            session = manager.activate(prefs.license_key.strip())
            sync_license_to_native_modules()
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
        from .licensing import sync_license_to_native_modules

        manager = get_license_manager()
        manager.deactivate()
        sync_license_to_native_modules()
        self.report({"INFO"}, "License deactivated.")
        _refresh_ui()
        return {"FINISHED"}


def _get_license_status():
    """Return license status dict safe for use during draw()."""
    try:
        from .licensing.manager import get_license_manager
        return get_license_manager().get_status()
    except Exception:
        return {
            "activated": False,
            "product": "",
            "tier": "",
            "license_id": "",
            "device_name": "",
            "features": {},
        }


def _draw_binary_status(box, module_name, label):
    """Draw the status and download button for a native binary."""
    try:
        from .native.downloader import get_download_status
        status = get_download_status(module_name)
    except Exception:
        status = "unknown"

    row = box.row()
    if status == "available":
        row.label(text=f"{label}: Installed", icon="CHECKMARK")
    elif status == "downloadable":
        row.label(text=f"{label}: Not installed", icon="ERROR")
        row.operator(
            RIG2_OT_download_native.bl_idname,
            text="Download",
            icon="IMPORT",
        ).module_name = module_name
    else:
        row.label(text=f"{label}: Unavailable (activate license first)", icon="LOCKED")


class RIG2_OT_download_native(bpy.types.Operator):
    bl_idname = "rig2.download_native"
    bl_label = "Download Native Binary"
    bl_description = "Download a native binary via your license"
    bl_options = {"REGISTER", "INTERNAL"}

    module_name: bpy.props.StringProperty()

    def execute(self, context):
        import traceback
        from .native.downloader import ensure_native_binary

        try:
            ok = ensure_native_binary(self.module_name)
            if ok:
                self.report({"INFO"}, f"Downloaded {self.module_name}. Restart Blender or reload the addon.")
            else:
                self.report({"ERROR"}, f"Could not download {self.module_name}.")
        except Exception as exc:
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
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def get_preferences():
    addon_name = __package__.partition('.')[0] if __package__ else "rig2_addons"
    addon = bpy.context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


from .core.registration import register_classes, unregister_classes

classes = (
    Rig2AddonPreferences,
    RIG2_OT_activate_license,
    RIG2_OT_deactivate_license,
    RIG2_OT_download_native,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
