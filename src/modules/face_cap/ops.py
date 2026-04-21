import bpy
import json
from bpy_extras.io_utils import ImportHelper

from ...core.constants import IDENTITY_QUATERNION, INTERNAL_KEYS
from ...core.registration import register_classes, unregister_classes
from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from .props import (
    ensure_face_cap_binding_items,
    get_face_cap_bindings,
    set_face_cap_bindings,
    sync_face_cap_bindings_to_scene_prop,
)
from .runtime import _clamp01, _sanitize_head_quaternion, get_runtime_service

# Constants moved to core.constants


def _iter_face_actions(obj):
    animation_data = getattr(obj, "animation_data", None)
    if not animation_data:
        return

    seen = set()
    if animation_data.action:
        seen.add(animation_data.action)
        yield animation_data.action

    for track in animation_data.nla_tracks:
        for strip in track.strips:
            action = getattr(strip, "action", None)
            if action and action not in seen:
                seen.add(action)
                yield action


def _get_target_props(face_bone):
    return [key for key in face_bone.keys() if key not in INTERNAL_KEYS]


def _get_scene_fps(scene):
    render = getattr(scene, "render", None)
    if not render:
        return 24.0

    fps = max(1, int(getattr(render, "fps", 24) or 24))
    fps_base = float(getattr(render, "fps_base", 1.0) or 1.0)
    if abs(fps_base) <= 1e-8:
        fps_base = 1.0
    return float(fps) / fps_base


def _extract_schema_names(payload):
    candidates = []
    if isinstance(payload, dict):
        candidates.extend(
            [
                payload.get("schema"),
                payload.get("blendshapeNames"),
                payload.get("blendshapesSchema"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, list):
            return [str(name) for name in candidate if isinstance(name, (str, int, float))]
        if isinstance(candidate, dict):
            for key in ("blendshapeNames", "names", "channels"):
                names = candidate.get(key)
                if isinstance(names, list):
                    return [str(name) for name in names if isinstance(name, (str, int, float))]
    return []


def _extract_video_fps(payload):
    if not isinstance(payload, dict):
        return None

    video_payload = payload.get("video")
    if isinstance(video_payload, dict):
        for key in ("frameRate", "fps"):
            try:
                fps = float(video_payload.get(key))
            except Exception:
                continue
            if fps > 0.0:
                return fps

    for key in (
        "videoFps",
        "videoFPS",
        "videoFrameRate",
        "frameRate",
        "fps",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            for nested_key in ("value", "fps", "frameRate"):
                nested_value = value.get(nested_key)
                try:
                    fps = float(nested_value)
                except Exception:
                    continue
                if fps > 0.0:
                    return fps
        try:
            fps = float(value)
        except Exception:
            continue
        if fps > 0.0:
            return fps
    return None


def _extract_faces(frame_payload):
    if not isinstance(frame_payload, dict):
        return []

    faces = frame_payload.get("faces")
    if isinstance(faces, list):
        return faces

    compact_faces = frame_payload.get("f")
    if isinstance(compact_faces, list):
        return compact_faces

    face = frame_payload.get("face")
    if isinstance(face, dict):
        return [face]

    return []


def _extract_frame_position(frame_payload, fallback_index, video_fps):
    if not isinstance(frame_payload, dict):
        return float(fallback_index)

    for key in ("frame", "frameIndex", "videoFrame", "position", "i"):
        value = frame_payload.get(key)
        try:
            return float(value)
        except Exception:
            pass

    for key in ("timeSeconds", "time", "timestampSeconds", "t"):
        value = frame_payload.get(key)
        try:
            return float(value) * float(video_fps)
        except Exception:
            pass

    for key in ("timestampMs", "timeMs", "ts"):
        value = frame_payload.get(key)
        try:
            return (float(value) / 1000.0) * float(video_fps)
        except Exception:
            pass

    return float(fallback_index)


def _blendshapes_from_payload(payload, schema_names):
    if isinstance(payload, dict):
        result = {}
        for key, value in payload.items():
            try:
                result[str(key)] = _clamp01(value)
            except Exception:
                continue
        return result

    if isinstance(payload, list):
        result = {}
        for index, value in enumerate(payload):
            if index >= len(schema_names):
                break
            try:
                result[str(schema_names[index])] = _clamp01(value)
            except Exception:
                continue
        return result

    return {}


def _normalize_head_quaternion(face_payload):
    if not isinstance(face_payload, dict):
        return None

    candidates = [
        face_payload.get("headQuaternion"),
        face_payload.get("quaternionWxyz"),
    ]

    head_pose = face_payload.get("headPose")
    if isinstance(head_pose, dict):
        candidates.extend(
            [
                head_pose.get("quaternionWxyz"),
                head_pose.get("headQuaternion"),
            ]
        )

    compact_head_pose = face_payload.get("hp")
    if isinstance(compact_head_pose, (list, tuple)) and len(compact_head_pose) >= 7:
        candidates.append(
            {
                "w": compact_head_pose[3],
                "x": compact_head_pose[4],
                "y": compact_head_pose[5],
                "z": compact_head_pose[6],
            }
        )

    for candidate in candidates:
        sanitized = _sanitize_head_quaternion(candidate)
        if sanitized is not None:
            return sanitized

        if isinstance(candidate, (list, tuple)) and len(candidate) >= 4:
            sanitized = _sanitize_head_quaternion(
                {
                    "w": candidate[0],
                    "x": candidate[1],
                    "y": candidate[2],
                    "z": candidate[3],
                }
            )
            if sanitized is not None:
                return sanitized

    return None


def _normalize_face_payload(face_payload, schema_names):
    if not isinstance(face_payload, dict):
        return {"index": 0, "blendshapes": {}, "head_quaternion": None}

    blendshape_payload = face_payload.get("blendshapes")
    if blendshape_payload is None:
        blendshape_payload = face_payload.get("blendshapeValues")
    if blendshape_payload is None:
        blendshape_payload = face_payload.get("b")

    try:
        face_index = int(face_payload.get("index", face_payload.get("i", 0)))
    except Exception:
        face_index = 0

    return {
        "index": max(0, face_index),
        "blendshapes": _blendshapes_from_payload(blendshape_payload, schema_names),
        "head_quaternion": _normalize_head_quaternion(face_payload),
    }


def _extract_frame_payloads(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("frames", "packets", "samples"):
            frames = payload.get(key)
            if isinstance(frames, list):
                return frames
    return []


def _load_offline_face_cap_payload(filepath):
    with open(filepath, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    schema_names = _extract_schema_names(payload)
    video_fps = _extract_video_fps(payload)
    if video_fps is None:
        video_fps = 30.0

    frames = []
    for fallback_index, frame_payload in enumerate(_extract_frame_payloads(payload)):
        source_frame = _extract_frame_position(frame_payload, fallback_index, video_fps)
        frames.append(
            {
                "source_frame": source_frame,
                "faces": [
                    _normalize_face_payload(face_payload, schema_names)
                    for face_payload in _extract_faces(frame_payload)
                ],
            }
        )

    return {
        "schema_names": schema_names,
        "video_fps": video_fps,
        "frames": frames,
    }


def _collect_binding_targets(scene):
    targets = []
    objects = getattr(getattr(bpy, "data", None), "objects", None)
    if objects is None:
        return targets

    for binding in get_face_cap_bindings(scene):
        obj = objects.get(binding["rig_name"])
        if not obj or not is_rig2_armature(obj):
            continue

        pose = getattr(obj, "pose", None)
        if not pose:
            continue

        face_bone = pose.bones.get("Face_BlendShapes")
        if not face_bone:
            continue

        targets.append(
            {
                "face_index": binding["face_index"],
                "obj": obj,
                "face_bone": face_bone,
                "prop_names": _get_target_props(face_bone),
            }
        )
    return targets


class RIG2_OT_FaceCapAddBinding(bpy.types.Operator):
    bl_idname = "rig2.face_cap_add_binding"
    bl_label = "New"
    bl_description = "Add a new face capture binding row"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        ensure_face_cap_binding_items(context.scene)
        items = getattr(context.scene, "rig2_face_cap_binding_items", None)
        if items is None:
            self.report({"ERROR"}, _f("Face Capture binding list is not registered"))
            return {"CANCELLED"}

        item = items.add()
        obj = get_context_object(context)
        if is_rig2_armature(obj):
            item.rig = obj
        item.face_index = 0
        sync_face_cap_bindings_to_scene_prop(context.scene)
        get_runtime_service().request_reapply()
        self.report({"INFO"}, _f("Added new face binding row"))
        return {"FINISHED"}


class RIG2_OT_FaceCapRemoveBinding(bpy.types.Operator):
    bl_idname = "rig2.face_cap_remove_binding"
    bl_label = "Remove Face Binding"
    bl_description = "Remove a face capture binding from the scene list"

    binding_index: bpy.props.IntProperty(default=-1, min=-1)

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        ensure_face_cap_binding_items(context.scene)
        items = getattr(context.scene, "rig2_face_cap_binding_items", None)
        if items is None:
            self.report({"ERROR"}, _f("Face Capture binding list is not registered"))
            return {"CANCELLED"}

        if self.binding_index < 0 or self.binding_index >= len(items):
            self.report({"ERROR"}, _f("Face binding index is out of range"))
            return {"CANCELLED"}

        removed = items[self.binding_index]
        removed_name = removed.rig.name if getattr(removed, "rig", None) else ""
        removed_face_index = int(getattr(removed, "face_index", 0))
        items.remove(self.binding_index)
        sync_face_cap_bindings_to_scene_prop(context.scene)
        get_runtime_service().request_reapply()
        self.report(
            {"INFO"},
            _f(
                "Removed face binding: Face {face_index} -> {name}",
                face_index=removed_face_index,
                name=removed_name,
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapClearBindings(bpy.types.Operator):
    bl_idname = "rig2.face_cap_clear_bindings"
    bl_label = "Clear Face Bindings"
    bl_description = "Clear every face capture binding stored on this scene"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        set_face_cap_bindings(context.scene, [])
        get_runtime_service().request_reapply()
        self.report({"INFO"}, _f("Face Capture bindings cleared"))
        return {"FINISHED"}


class RIG2_OT_FaceCapImportJson(bpy.types.Operator, ImportHelper):
    bl_idname = "rig2.face_cap_import_json"
    bl_label = "Import Face Capture JSON"
    bl_description = "Import offline face capture JSON and keyframe the bound Rig2 targets"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={"HIDDEN"},
        maxlen=255,
    )

    def execute(self, context):
        scene = context.scene
        targets = _collect_binding_targets(scene)
        if not targets:
            self.report({"ERROR"}, _f("No valid bound rig with Face_BlendShapes found"))
            return {"CANCELLED"}

        try:
            offline_data = _load_offline_face_cap_payload(self.filepath)
        except Exception as exc:
            self.report({"ERROR"}, _f("Failed to read Face Capture JSON: {error}", error=exc))
            return {"CANCELLED"}

        frames = offline_data["frames"]
        if not frames:
            self.report({"ERROR"}, _f("No face capture frames found in JSON"))
            return {"CANCELLED"}

        video_fps = max(1e-6, float(offline_data["video_fps"]))
        scene_fps = _get_scene_fps(scene)
        fps_scale = scene_fps / video_fps
        start_frame = float(scene.frame_current)
        inserted_frames = 0

        for frame_payload in frames:
            frame_number = start_frame + (float(frame_payload["source_frame"]) * fps_scale)
            faces = frame_payload["faces"]
            faces_by_index = {int(face.get("index", idx)): face for idx, face in enumerate(faces)}

            for target in targets:
                obj = target["obj"]
                face_bone = target["face_bone"]
                face_index = target["face_index"]
                face_payload = faces_by_index.get(face_index)
                blendshapes = dict(face_payload.get("blendshapes", {})) if face_payload else {}

                for prop_name in target["prop_names"]:
                    face_bone[prop_name] = blendshapes.get(prop_name, 0.0)
                    face_bone.keyframe_insert(data_path=f'["{prop_name}"]', frame=frame_number)

                target_head_quaternion = (
                    face_payload.get("head_quaternion") if face_payload else IDENTITY_QUATERNION
                )
                face_bone.rotation_mode = "QUATERNION"
                face_bone.rotation_quaternion = target_head_quaternion or IDENTITY_QUATERNION
                face_bone.keyframe_insert("rotation_quaternion", frame=frame_number)

                try:
                    obj.update_tag(refresh={"OBJECT", "DATA"})
                except Exception:
                    pass

            inserted_frames += 1

        if context.view_layer:
            context.view_layer.update()

        self.report(
            {"INFO"},
            _f(
                "Imported {frame_count} face capture frames at {video_fps:.3f} fps into {rig_count} bound rig(s)",
                frame_count=inserted_frames,
                video_fps=video_fps,
                rig_count=len(targets),
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapStartServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_start_server"
    bl_label = "Start Face Capture Receiver"
    bl_description = "Start the local face capture WebSocket receiver"

    def execute(self, context):
        settings = getattr(context.scene, "rig2_face_cap_settings", None)
        if settings is None:
            self.report({"ERROR"}, _f("Face Capture settings are not registered"))
            return {"CANCELLED"}

        service = get_runtime_service()
        service.start(settings=settings)
        binding_count = len(get_face_cap_bindings(context.scene))
        status = service.get_status_snapshot()
        local_ipv4_address = status.get("local_ipv4_address", "")
        receiver_host = local_ipv4_address or settings.listen_host
        self.report(
            {"INFO"},
            _f(
                "Face Capture receiver started on ws://{host}:{port} with {count} binding(s)",
                host=receiver_host,
                port=settings.listen_port,
                count=binding_count,
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapStopServer(bpy.types.Operator):
    bl_idname = "rig2.face_cap_stop_server"
    bl_label = "Stop Face Capture Receiver"
    bl_description = "Stop the local face capture WebSocket receiver"

    def execute(self, context):
        service = get_runtime_service()
        service.stop()
        self.report({"INFO"}, _f("Face Capture receiver stopped"))
        return {"FINISHED"}


class RIG2_OT_FaceCapApplyNow(bpy.types.Operator):
    bl_idname = "rig2.face_cap_apply_now"
    bl_label = "Apply Cached Face Packet"
    bl_description = "Apply the latest received blendshape packet to enabled Rig2 armatures immediately"

    def execute(self, context):
        service = get_runtime_service()
        service.apply_latest_data()
        self.report(
            {"INFO"},
            _f(
                "Applied cached face packet to {count} enabled rig(s)",
                count=service.count_enabled_rigs(),
            ),
        )
        return {"FINISHED"}


class RIG2_OT_FaceCapClearKeys(bpy.types.Operator):
    bl_idname = "rig2.face_cap_clear_keys"
    bl_label = "Clear Face Capture Keys"
    bl_description = "Delete all Face_BlendShapes custom property keyframes on the active Rig2 armature and reset them to zero"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = get_context_object(context)
        if not is_rig2_armature(obj):
            return False

        pose = getattr(obj, "pose", None)
        return bool(pose and pose.bones.get("Face_BlendShapes"))

    def execute(self, context):
        obj = get_context_object(context)
        face_bone = obj.pose.bones.get("Face_BlendShapes")
        if not face_bone:
            self.report({"ERROR"}, _f("Face_BlendShapes bone not found"))
            return {"CANCELLED"}

        prop_names = [key for key in face_bone.keys() if key not in INTERNAL_KEYS]
        for prop_name in prop_names:
            face_bone[prop_name] = 0.0

        face_bone.rotation_mode = "QUATERNION"
        face_bone.rotation_quaternion = IDENTITY_QUATERNION

        try:
            obj.update_tag(refresh={"OBJECT", "DATA"})
        except Exception:
            pass

        removed_curves = 0
        prop_prefix = 'pose.bones["Face_BlendShapes"]["'
        rotation_path = 'pose.bones["Face_BlendShapes"].rotation_quaternion'
        for action in _iter_face_actions(obj):
            for fcurve in list(action.fcurves):
                if fcurve.data_path.startswith(prop_prefix) or fcurve.data_path == rotation_path:
                    action.fcurves.remove(fcurve)
                    removed_curves += 1

        get_runtime_service().clear_cached_packet()

        if context.view_layer:
            context.view_layer.update()

        self.report(
            {"INFO"},
            _f(
                "Cleared {curve_count} face capture f-curves and reset {blendshape_count} blendshape values",
                curve_count=removed_curves,
                blendshape_count=len(prop_names),
            ),
        )
        return {"FINISHED"}


classes = (
    RIG2_OT_FaceCapAddBinding,
    RIG2_OT_FaceCapRemoveBinding,
    RIG2_OT_FaceCapClearBindings,
    RIG2_OT_FaceCapImportJson,
    RIG2_OT_FaceCapStartServer,
    RIG2_OT_FaceCapStopServer,
    RIG2_OT_FaceCapApplyNow,
    RIG2_OT_FaceCapClearKeys,
)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
