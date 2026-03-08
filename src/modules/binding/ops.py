import bpy
import os

class RIG2_OT_AppendRig(bpy.types.Operator):
    """Append the Rig2 collection from the addon assets"""
    bl_idname = "rig2.append_rig"
    bl_label = "Rig/2"
    bl_description = "Append Rig2 collection from assets"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # The asset is in the root assets folder
        # We need to find the root directory of the addon
        # This file is in src/modules/binding/
        current_dir = os.path.dirname(os.path.realpath(__file__))
        addon_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
        filepath = os.path.join(addon_root, "assets", "rig2-remake.blend")
        
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"Asset file not found: {filepath}")
            return {'CANCELLED'}

        collection_name = "Rig2"
        
        try:
            with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                if collection_name in data_from.collections:
                    data_to.collections = [collection_name]
                else:
                    self.report({'ERROR'}, f"Collection '{collection_name}' not found in asset file")
                    return {'CANCELLED'}

            for coll in data_to.collections:
                if coll is not None:
                    context.collection.children.link(coll)
                    for obj in coll.objects:
                        obj.select_set(True)
                        if obj.type == 'ARMATURE':
                            context.view_layer.objects.active = obj
            
            self.report({'INFO'}, "Rig2 Appended Successfully")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to append: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(RIG2_OT_AppendRig.bl_idname, text="Rig/2", icon='ARMATURE_DATA')

def register():
    bpy.utils.register_class(RIG2_OT_AppendRig)
    bpy.types.VIEW3D_MT_add.append(menu_func)

def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_func)
    bpy.utils.unregister_class(RIG2_OT_AppendRig)
