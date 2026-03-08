import bpy
from . import importer
from . import mi_to_fk

def register():
    try:
        bpy.utils.register_class(importer.MI_OT_ImportAction)
    except Exception:
        pass
    try:
        bpy.utils.register_class(importer.MI_OT_ImportConfirmDialog)
    except Exception:
        pass
    try:
        bpy.utils.register_class(mi_to_fk.MI_OT_BakeToFK)
    except Exception:
        pass

def unregister():
    try:
        bpy.utils.unregister_class(mi_to_fk.MI_OT_BakeToFK)
        bpy.utils.unregister_class(importer.MI_OT_ImportConfirmDialog)
        bpy.utils.unregister_class(importer.MI_OT_ImportAction)
    except:
        pass
