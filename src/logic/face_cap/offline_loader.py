import json

from .protocol import clamp01, sanitize_head_quaternion


def extract_schema_names(payload):
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


def extract_video_fps(payload):
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

    for key in ("videoFps", "videoFPS", "videoFrameRate", "frameRate", "fps"):
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


def extract_faces(frame_payload):
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


def extract_frame_position(frame_payload, fallback_index, video_fps):
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


def blendshapes_from_payload(payload, schema_names):
    if isinstance(payload, dict):
        result = {}
        for key, value in payload.items():
            try:
                result[str(key)] = clamp01(value)
            except Exception:
                continue
        return result

    if isinstance(payload, list):
        result = {}
        for index, value in enumerate(payload):
            if index >= len(schema_names):
                break
            try:
                result[str(schema_names[index])] = clamp01(value)
            except Exception:
                continue
        return result

    return {}


def normalize_head_quaternion(face_payload):
    if not isinstance(face_payload, dict):
        return None

    candidates = [face_payload.get("headQuaternion"), face_payload.get("quaternionWxyz")]

    head_pose = face_payload.get("headPose")
    if isinstance(head_pose, dict):
        candidates.extend([head_pose.get("quaternionWxyz"), head_pose.get("headQuaternion")])

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
        sanitized = sanitize_head_quaternion(candidate)
        if sanitized is not None:
            return sanitized

        if isinstance(candidate, (list, tuple)) and len(candidate) >= 4:
            sanitized = sanitize_head_quaternion(
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


def normalize_face_payload(face_payload, schema_names):
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
        "blendshapes": blendshapes_from_payload(blendshape_payload, schema_names),
        "head_quaternion": normalize_head_quaternion(face_payload),
    }


def extract_frame_payloads(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("frames", "packets", "samples"):
            frames = payload.get(key)
            if isinstance(frames, list):
                return frames
    return []


def load_offline_face_cap_payload(filepath):
    with open(filepath, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    schema_names = extract_schema_names(payload)
    video_fps = extract_video_fps(payload)
    if video_fps is None:
        video_fps = 30.0

    frames = []
    for fallback_index, frame_payload in enumerate(extract_frame_payloads(payload)):
        source_frame = extract_frame_position(frame_payload, fallback_index, video_fps)
        frames.append(
            {
                "source_frame": source_frame,
                "faces": [
                    normalize_face_payload(face_payload, schema_names)
                    for face_payload in extract_faces(frame_payload)
                ],
            }
        )

    return {
        "schema_names": schema_names,
        "video_fps": video_fps,
        "frames": frames,
    }

