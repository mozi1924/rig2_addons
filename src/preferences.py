import bpy
from bpy.props import BoolProperty
import os

from .i18n import format_text as _f
from .i18n import iface as _

class Rig2AddonPreferences(bpy.types.AddonPreferences):
    # Get the root package name (e.g., 'rig2_addons_remake')
    bl_idname = __package__.split('.')[0]

    show_n_panel: BoolProperty(
        name="Show N-Panel",
        description="Show the Rig2 control panel in the 3D View side panel (N-key)",
        default=True,
    )

    show_logic_props: BoolProperty(
        name="Show all logic properties",
        description="Show all custom properties for the 'logic' bone in the Danger Zone",
        default=False,
    )

    def draw(self, context):
        from .modules.face_cap.runtime import get_runtime_service

        layout = self.layout
        column = layout.column()
        column.prop(self, "show_n_panel")
        column.prop(self, "show_logic_props")

        status = get_runtime_service().get_status_snapshot()
        wt_box = layout.box()
        wt_box.label(text=_("WebTransport"), icon="NETWORK_DRIVE")
        wt_box.label(
            text=_f(
                "{label}: {value}",
                label=_("Dependency"),
                value=_("Installed") if status["webtransport_dependency_ready"] else _("Not installed"),
            )
        )
        if status["webtransport_dependency_origin"]:
            wt_box.label(
                text=_f(
                    "{label}: {value}",
                    label=_("Origin"),
                    value=os.path.basename(status["webtransport_dependency_origin"]),
                )
            )
        wt_box.label(
            text=_f(
                "{label}: {value}",
                label=_("Certificate"),
                value=_("Bundled") if status["webtransport_cert_ready"] else _("Missing"),
            )
        )
        wt_box.label(
            text=_f(
                "{label}: {value}",
                label=_("CA File"),
                value=os.path.basename(status["webtransport_ca_cert_der_path"]),
            )
        )
        wt_box.label(text=_("Bundled WT cert is for localhost / 127.0.0.1 only."))
        wt_actions = wt_box.row(align=True)
        wt_actions.operator("rig2.face_cap_install_webtransport_dependency", icon="IMPORT")
        wt_actions.operator("rig2.face_cap_uninstall_webtransport_dependency", icon="TRASH")

def get_preferences():
    addon_name = __package__.split('.')[0]
    addon = bpy.context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None

def register():
    try:
        bpy.utils.register_class(Rig2AddonPreferences)
    except ValueError:
        try:
            bpy.utils.unregister_class(Rig2AddonPreferences)
        except Exception:
            pass
        bpy.utils.register_class(Rig2AddonPreferences)

def unregister():
    try:
        bpy.utils.unregister_class(Rig2AddonPreferences)
    except Exception:
        pass
