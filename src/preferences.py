import bpy


class Rig2AddonPreferences(bpy.types.AddonPreferences):
    # Get the root package name robustly
    bl_idname = __package__.partition('.')[0] if __package__ else "rig2_addons"

    show_n_panel = bpy.props.BoolProperty(
        name="Show N-Panel",
        description="Show the Rig2 control panel in the 3D View side panel (N-key)",
        default=True,
    )

    show_logic_props = bpy.props.BoolProperty(
        name="Show all logic properties",
        description="Show all custom properties for the 'logic' bone in the Danger Zone",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        column = layout.column()
        column.prop(self, "show_n_panel")
        column.prop(self, "show_logic_props")

def get_preferences():
    addon_name = __package__.partition('.')[0] if __package__ else "rig2_addons"
    addon = bpy.context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None

from .core.registration import register_classes, unregister_classes

classes = (
    Rig2AddonPreferences,
)

def register():
    register_classes(classes)

def unregister():
    unregister_classes(classes)
