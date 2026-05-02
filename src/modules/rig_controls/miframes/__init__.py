from ....core.registration import register_classes, unregister_classes
from . import importer, mi_to_fk

_CLASSES = (
    importer.MI_OT_ImportAction,
    importer.MI_OT_ImportConfirmDialog,
    mi_to_fk.MI_OT_BakeToFK,
)

def register():
    register_classes(_CLASSES, module_name="MIFrames")

def unregister():
    unregister_classes(_CLASSES)
