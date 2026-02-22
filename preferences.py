import bpy
from bpy.props import BoolProperty

class Rig2AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

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
    return bpy.context.preferences.addons[__package__].preferences

def register():
    bpy.utils.register_class(Rig2AddonPreferences)

def unregister():
    bpy.utils.unregister_class(Rig2AddonPreferences)
