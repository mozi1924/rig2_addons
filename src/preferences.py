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

        box.separator()
        box.label(text="Settings", icon="PREFERENCES")
        column = box.column()
        column.prop(self, "show_n_panel")
        column.prop(self, "show_logic_props")


class RIG2_OT_activate_license(bpy.types.Operator):
    bl_idname = "rig2.activate_license"
    bl_label = "Activate License"
    bl_description = "Activate a Rig2 license key via Orbisauth"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        prefs = get_preferences()
        if not prefs or not prefs.license_key.strip():
            self.report({"ERROR"}, "Please enter a license key.")
            return {"CANCELLED"}

        from .licensing.manager import get_license_manager

        manager = get_license_manager()
        try:
            session = manager.activate(prefs.license_key.strip())
            self.report(
                {"INFO"},
                f"License activated: {session.product} ({session.tier})",
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Activation failed: {exc}")
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

        manager = get_license_manager()
        manager.deactivate()
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
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
