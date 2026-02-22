import bpy
from bpy.props import BoolProperty
import os

class Rig2AddonPreferences(bpy.types.AddonPreferences):
    # Get the root package name (e.g., 'rig2_addons_remake')
    bl_idname = __package__.split('.')[0]

    show_n_panel: BoolProperty(
        name="Show N-Panel",
        description="Show the Rig2 control panel in the 3D View side panel (N-key)",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        column = layout.column()
        column.prop(self, "show_n_panel")

def get_preferences():
    addon_name = __package__.split('.')[0]
    return bpy.context.preferences.addons[addon_name].preferences

def register():
    bpy.utils.register_class(Rig2AddonPreferences)

def unregister():
    bpy.utils.unregister_class(Rig2AddonPreferences)
