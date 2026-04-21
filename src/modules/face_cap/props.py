import json

import bpy

from ...core.utils import is_rig2_armature

FACE_CAP_BINDINGS_PROP = "rig2_face_cap_bindings"
_BINDING_SYNC_LOCK = set()


def _target_rig_poll(_self, obj):
    return is_rig2_armature(obj)


def _update_face_cap_runtime(_self, _context):
    try:
        from .runtime import get_runtime_service

        get_runtime_service().request_reapply()
    except Exception:
        pass


def _find_scene_for_binding_item(item):
    scenes = getattr(getattr(bpy, "data", None), "scenes", None) or []
    item_pointer = item.as_pointer()
    for scene in scenes:
        for binding in getattr(scene, "rig2_face_cap_binding_items", []):
            if binding.as_pointer() == item_pointer:
                return scene
    return None


def _update_face_cap_binding_item(self, _context):
    scene = _find_scene_for_binding_item(self)
    if scene is None:
        return

    sync_face_cap_bindings_to_scene_prop(scene)
    _update_face_cap_runtime(self, _context)


class Rig2FaceCapSettings(bpy.types.PropertyGroup):
    listen_host: bpy.props.StringProperty(
        name="Host",
        description="Local interface used by the face capture WebSocket receiver",
        default="0.0.0.0",
    )

    listen_port: bpy.props.IntProperty(
        name="Port",
        description="Local port used by the face capture WebSocket receiver",
        default=9000,
        min=1,
        max=65535,
    )

    binding_rig: bpy.props.PointerProperty(
        name="Target Rig",
        description="Rig2 armature used when adding a face capture binding",
        type=bpy.types.Object,
        poll=_target_rig_poll,
    )

    binding_face_index: bpy.props.IntProperty(
        name="Face Index",
        description="Incoming face index used when adding a face capture binding",
        default=0,
        min=0,
    )


class Rig2FaceCapBindingItem(bpy.types.PropertyGroup):
    rig: bpy.props.PointerProperty(
        name="Rig",
        description="Rig2 armature used by this face capture binding",
        type=bpy.types.Object,
        poll=_target_rig_poll,
        update=_update_face_cap_binding_item,
    )

    face_index: bpy.props.IntProperty(
        name="Face Index",
        description="Incoming face index used by this face capture binding",
        default=0,
        min=0,
        update=_update_face_cap_binding_item,
    )


def get_face_cap_settings(scene):
    return getattr(scene, "rig2_face_cap_settings", None)


def _sanitize_binding_entry(entry):
    if not isinstance(entry, dict):
        return None

    rig_name = str(entry.get("rig_name", "")).strip()
    if not rig_name:
        return None

    try:
        face_index = max(0, int(entry.get("face_index", 0)))
    except Exception:
        face_index = 0

    return {
        "face_index": face_index,
        "rig_name": rig_name,
    }


def get_face_cap_bindings(scene):
    if scene is None:
        return []

    ensure_face_cap_binding_items(scene)

    bindings = []
    for item in getattr(scene, "rig2_face_cap_binding_items", []):
        rig = getattr(item, "rig", None)
        sanitized = _sanitize_binding_entry(
            {
                "face_index": getattr(item, "face_index", 0),
                "rig_name": getattr(rig, "name", ""),
            }
        )
        if sanitized is not None:
            bindings.append(sanitized)
    return bindings


def set_face_cap_bindings(scene, bindings):
    if scene is None:
        return

    sanitized = []
    for entry in bindings or []:
        normalized = _sanitize_binding_entry(entry)
        if normalized is not None:
            sanitized.append(normalized)

    scene[FACE_CAP_BINDINGS_PROP] = json.dumps(sanitized, ensure_ascii=True)
    sync_face_cap_bindings_from_scene_prop(scene)


def ensure_face_cap_binding_items(scene):
    if scene is None:
        return

    collection = getattr(scene, "rig2_face_cap_binding_items", None)
    if collection is None:
        return
    if len(collection) > 0:
        return

    raw_value = scene.get(FACE_CAP_BINDINGS_PROP, "[]")
    if isinstance(raw_value, list):
        data = raw_value
    else:
        try:
            data = json.loads(raw_value or "[]")
        except Exception:
            data = []

    if not data:
        return

    sync_face_cap_bindings_from_scene_prop(scene)


def sync_face_cap_bindings_from_scene_prop(scene):
    if scene is None:
        return

    scene_pointer = scene.as_pointer()
    if scene_pointer in _BINDING_SYNC_LOCK:
        return

    collection = getattr(scene, "rig2_face_cap_binding_items", None)
    if collection is None:
        return

    raw_value = scene.get(FACE_CAP_BINDINGS_PROP, "[]")
    if isinstance(raw_value, list):
        data = raw_value
    else:
        try:
            data = json.loads(raw_value or "[]")
        except Exception:
            data = []

    sanitized = []
    for entry in data:
        normalized = _sanitize_binding_entry(entry)
        if normalized is not None:
            sanitized.append(normalized)

    objects = getattr(getattr(bpy, "data", None), "objects", None)
    _BINDING_SYNC_LOCK.add(scene_pointer)
    try:
        collection.clear()
        for entry in sanitized:
            item = collection.add()
            item.face_index = entry["face_index"]
            if objects is not None:
                item.rig = objects.get(entry["rig_name"])
    finally:
        _BINDING_SYNC_LOCK.discard(scene_pointer)


def sync_face_cap_bindings_to_scene_prop(scene):
    if scene is None:
        return

    scene_pointer = scene.as_pointer()
    if scene_pointer in _BINDING_SYNC_LOCK:
        return

    collection = getattr(scene, "rig2_face_cap_binding_items", None)
    if collection is None:
        return

    sanitized = []
    for item in collection:
        rig = getattr(item, "rig", None)
        normalized = _sanitize_binding_entry(
            {
                "face_index": getattr(item, "face_index", 0),
                "rig_name": getattr(rig, "name", ""),
            }
        )
        if normalized is not None:
            sanitized.append(normalized)

    _BINDING_SYNC_LOCK.add(scene_pointer)
    try:
        scene[FACE_CAP_BINDINGS_PROP] = json.dumps(sanitized, ensure_ascii=True)
    finally:
        _BINDING_SYNC_LOCK.discard(scene_pointer)


classes = (
    Rig2FaceCapSettings,
    Rig2FaceCapBindingItem,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"Rig2 FaceCap register error for {cls.__name__}: {exc}")

    if not hasattr(bpy.types.Scene, "rig2_face_cap_settings"):
        bpy.types.Scene.rig2_face_cap_settings = bpy.props.PointerProperty(
            type=Rig2FaceCapSettings,
        )
    if not hasattr(bpy.types.Scene, "rig2_face_cap_binding_items"):
        bpy.types.Scene.rig2_face_cap_binding_items = bpy.props.CollectionProperty(
            type=Rig2FaceCapBindingItem,
        )


def unregister():
    if hasattr(bpy.types.Scene, "rig2_face_cap_settings"):
        del bpy.types.Scene.rig2_face_cap_settings
    if hasattr(bpy.types.Scene, "rig2_face_cap_binding_items"):
        del bpy.types.Scene.rig2_face_cap_binding_items

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
