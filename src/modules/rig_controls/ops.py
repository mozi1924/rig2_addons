import bpy
from .props import PROPERTY_MAP
from .miframes.importer import MI_OT_ImportAction

# Bone name key -> actual pose bone name mapping
BONE_NAME_MAP = {
    "limbs": "prop.limbs",
    "head": "prop.head",
    "misc": "prop.misc",
    "performance": "prop.prop"
}

INTERNAL_KEYS = {'_RNA_UI', 'is_rig2'}

def has_driver(obj, bone_name, prop_name):
    """Check if a custom property on a pose bone is controlled by a driver."""
    if not obj.animation_data:
        return False
    data_path = f'pose.bones["{bone_name}"]["{prop_name}"]'
    for drv in obj.animation_data.drivers:
        if drv.data_path == data_path:
            return True
    return False

class Rig2Controller:
    @staticmethod
    def reset_to_defaults(context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return
            
        pose_bones = obj.pose.bones
        
        for bone_name_key, prop_list in PROPERTY_MAP.items():
            real_bone_name = BONE_NAME_MAP.get(bone_name_key)
            
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
        
        # Also reset 'logic' bone if it exists (skip driven properties)
        if "logic" in pose_bones:
            bone = pose_bones["logic"]
            for p in bone.keys():
                if p not in INTERNAL_KEYS and not has_driver(obj, "logic", p):
                    try:
                        ui_data = bone.id_properties_ui(p).as_dict()
                        default_val = ui_data.get('default', bone[p])
                        bone[p] = default_val
                    except:
                        pass

    @staticmethod
    def keyframe_all_props(context):
        """Keyframe all Rig2 custom properties at the current frame."""
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return 0
        
        pose_bones = obj.pose.bones
        frame = context.scene.frame_current
        count = 0

        # Keyframe all prop bones
        for real_bone_name in BONE_NAME_MAP.values():
            if real_bone_name in pose_bones:
                bone = pose_bones[real_bone_name]
                for prop_name in bone.keys():
                    if prop_name not in INTERNAL_KEYS:
                        try:
                            bone.keyframe_insert(
                                data_path=f'["{prop_name}"]',
                                frame=frame
                            )
                            count += 1
                        except Exception:
                            pass

        # Keyframe logic bone properties (skip driven properties)
        if "logic" in pose_bones:
            bone = pose_bones["logic"]
            for prop_name in bone.keys():
                if prop_name not in INTERNAL_KEYS and not has_driver(obj, "logic", prop_name):
                    try:
                        bone.keyframe_insert(
                            data_path=f'["{prop_name}"]',
                            frame=frame
                        )
                        count += 1
                    except Exception:
                        pass

        return count

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

class RIG2_OT_KeyframeState(bpy.types.Operator):
    bl_idname = "rig2.keyframe_state"
    bl_label = "Keyframe Current State"
    bl_description = "Insert a keyframe for all Rig2 properties at the current frame. Useful for smooth transitions when splicing multiple animation clips."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = Rig2Controller.keyframe_all_props(context)
        if count > 0:
            frame = context.scene.frame_current
            self.report({'INFO'}, f"Keyframed {count} properties at frame {frame}")
        else:
            self.report({'WARNING'}, "No properties found to keyframe")
        return {'FINISHED'}

classes = (
    RIG2_OT_ResetProperties,
    RIG2_OT_KeyframeState,
    MI_OT_ImportAction,
)

def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"Rig2 Error registering {cls}: {e}")

def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            pass # Silently fail if not registered or already unregistered
