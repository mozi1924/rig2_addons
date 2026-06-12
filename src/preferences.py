import bpy

from .core.utils import tag_context_redraw


def _resolve_addon_module_name() -> str:
    """
    Resolve addon module key for both legacy and extension installs.

    Legacy package example:
      rig2_addons.src
    Extension package example:
      bl_ext.repo_name.rig2_addons.src
    """
    package_name = __package__ or ""
    if package_name.endswith(".src"):
        return package_name[: -len(".src")]
    if package_name:
        return package_name
    return "rig2_addons"


ADDON_MODULE_NAME = _resolve_addon_module_name()
ADDON_FALLBACK_NAME = "rig2_addons"


class Rig2AddonPreferences(bpy.types.AddonPreferences):
    # Must match addon module key in bpy.context.preferences.addons.
    bl_idname = ADDON_MODULE_NAME

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

    def draw(self, context):
        layout = self.layout

        # -- Dev Mode banner --
        box = layout.box()
        box.label(text="Rig2 — Open Source (all features active)", icon="CHECKMARK")

        # -- Features status --
        feature_box = layout.box()
        feature_box.label(text="Features", icon="FILE_CACHE")
        for name, label in [("face_cap", "Face Capture"), ("miframes", "MIFrames"), ("r2bb", "R2BB")]:
            row = feature_box.row()
            row.label(text=f"{label}: Ready", icon="CHECKMARK")

        # -- Settings --
        settings_box = layout.box()
        settings_box.label(text="Settings", icon="PREFERENCES")
        column = settings_box.column()
        column.prop(self, "show_n_panel")
        column.prop(self, "show_logic_props")


def _refresh_ui():
    """Tag all windows for redraw so the preferences panel updates."""
    tag_context_redraw()


def get_preferences():
    addons = bpy.context.preferences.addons
    addon = addons.get(ADDON_MODULE_NAME)
    if addon:
        return addon.preferences
    addon = addons.get(ADDON_FALLBACK_NAME)
    return addon.preferences if addon else None


from .core.registration import register_classes, unregister_classes

classes = (
    Rig2AddonPreferences,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
