import bpy
from .props import PROPERTY_MAP

class Rig2Controller:
    @staticmethod
    def reset_to_defaults(context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return
            
        pose_bones = obj.pose.bones
        
        for bone_name_key, prop_list in PROPERTY_MAP.items():
            real_bone_name = {
                "limbs": "prop.limbs",
                "head": "prop.head",
                "misc": "prop.misc",
                "performance": "prop.prop"
            }.get(bone_name_key)
            
            if real_bone_name and real_bone_name in pose_bones:
                bone = pose_bones[real_bone_name]
                for p in prop_list:
                    if p in bone:
                        try:
                            ui_data = bone.id_properties_ui(p).as_dict()
                            default_val = ui_data.get('default', bone[p])
                            bone[p] = default_val
                        except:
                            pass
        
        # Also reset 'logic' bone if it exists
        if "logic" in pose_bones:
            bone = pose_bones["logic"]
            internal_keys = {'_RNA_UI', 'is_rig2'}
            for p in bone.keys():
                if p not in internal_keys:
                    try:
                        ui_data = bone.id_properties_ui(p).as_dict()
                        default_val = ui_data.get('default', bone[p])
                        bone[p] = default_val
                    except:
                        pass

class RIG2_OT_ResetProperties(bpy.types.Operator):
    bl_idname = "rig2.reset_props"
    bl_label = "Reset ALL Rig2 Properties?"
    bl_description = "Reset all properties to their original bone defaults."
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        Rig2Controller.reset_to_defaults(context)
        self.report({'INFO'}, "All properties reset to defaults")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(RIG2_OT_ResetProperties)

def unregister():
    bpy.utils.unregister_class(RIG2_OT_ResetProperties)
