import threading
import time

import bpy
from bpy.app.handlers import persistent

from ...core.constants import INTERNAL_KEYS
from ...core.utils import is_rig2_armature, refresh_rig_driver_batch
from ...services.face_cap_service import get_face_cap_backend_service
from .props import get_face_cap_bindings, get_face_cap_settings

FACE_CAP_TIMER_INTERVAL = 1.0 / 60.0
FACE_CAP_WEBSOCKET_DEFAULT_PORT = 9000
FACE_CAP_STARTUP_TIMEOUT_SECONDS = 1.0
FACE_CAP_STARTUP_POLL_INTERVAL_SECONDS = 0.05

def _is_face_cap_enabled(obj):
    if not is_rig2_armature(obj):
        return False

    pose = getattr(obj, "pose", None)
    if not pose:
        return False

    logic_bone = pose.bones.get("logic")
    face_bone = pose.bones.get("Face_BlendShapes")
    if not logic_bone or not face_bone:
        return False

    return float(logic_bone.get("face_cap", 0.0)) >= 0.999


def _get_scene_settings():
    scene = getattr(bpy.context, "scene", None)
    if scene:
        settings = get_face_cap_settings(scene)
        if settings is not None:
            return settings

    scenes = getattr(getattr(bpy, "data", None), "scenes", None)
    if scenes:
        return get_face_cap_settings(scenes[0])

    return None


def _get_scene_bindings():
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        return get_face_cap_bindings(scene)

    scenes = getattr(getattr(bpy, "data", None), "scenes", None)
    if scenes:
        return get_face_cap_bindings(scenes[0])

    return []


def _iter_face_cap_targets():
    seen = set()
    objects = getattr(getattr(bpy, "data", None), "objects", None)
    if objects is None:
        return

    for binding in _get_scene_bindings():
        obj = objects.get(binding["rig_name"])
        if not obj or not _is_face_cap_enabled(obj):
            continue

        key = (binding["face_index"], obj.name_full)
        if key in seen:
            continue
        seen.add(key)

        yield binding["face_index"], obj, obj.pose.bones["Face_BlendShapes"]


def _get_binding_status_snapshot():
    bindings = []
    objects = getattr(getattr(bpy, "data", None), "objects", None)
    for binding in _get_scene_bindings():
        obj = objects.get(binding["rig_name"]) if objects is not None else None
        bindings.append(
            {
                "face_index": binding["face_index"],
                "rig_name": binding["rig_name"],
                "missing": not bool(obj and is_rig2_armature(obj)),
            }
        )
    return bindings


def _get_target_props(face_bone):
    return [key for key in face_bone.keys() if key not in INTERNAL_KEYS]


def _get_face_blendshape_bone(obj):
    pose = getattr(obj, "pose", None)
    if not pose:
        return None

    return pose.bones.get("Face_BlendShapes")


class FaceCapRuntimeService:
    def __init__(self):
        self._lock = threading.Lock()
        self._native_receiver_enabled = False
        self._native_host = ""
        self._native_port = 0
        self._native_is_listening = False
        self._native_bind_failed = False
        self._timer_registered = False
        self._latest_packet_data = None
        self._latest_faces = []
        self._last_face_count = 0
        self._packet_count = 0
        self._dropped_packet_count = 0
        self._last_packet_time = 0.0
        self._last_sent_at = ""
        self._client_address = ""
        self._status_message = "Stopped"
        self._last_error = ""
        self._packet_revision = 0
        self._applied_revision = 0
        self._applied_packet_count = 0
        self._last_applied_faces = []
        self._last_applied_face_count = 0
        self._transport_mode = "websocket"
        self._transport_encoding = None
        self._local_ipv4_address = ""
        self._runtime_bindings = {}
        self.refresh_backend()

    def register(self):
        self.refresh_backend()
        self._ensure_timer()

    def unregister(self):
        self.stop()
        if self._timer_registered:
            try:
                bpy.app.timers.unregister(self._timer_callback)
            except Exception:
                pass
            self._timer_registered = False

    def _ensure_timer(self):
        if self._timer_registered:
            return

        bpy.app.timers.register(self._timer_callback, first_interval=0.1, persistent=True)
        self._timer_registered = True

    def get_status_snapshot(self):
        self.refresh_backend()

        with self._lock:
            if self._last_packet_time > 0.0:
                age_seconds = max(0.0, time.time() - self._last_packet_time)
            else:
                age_seconds = None

            return {
                "host": self._native_host,
                "port": self._native_port,
                "is_listening": self._native_is_listening,
                "bind_failed": self._native_bind_failed,
                "client_address": self._client_address,
                "packet_count": self._packet_count,
                "dropped_packet_count": self._dropped_packet_count,
                "applied_packet_count": self._applied_packet_count,
                "face_count": self._last_face_count,
                "last_sent_at": self._last_sent_at,
                "last_packet_age": age_seconds,
                "status_message": self._status_message,
                "last_error": self._last_error,
                "bindings": _get_binding_status_snapshot(),
                "transport_mode": self._transport_mode,
                "transport_encoding": self._transport_encoding,
                "local_ipv4_address": self._local_ipv4_address,
            }

    def clear_cached_packet(self):
        with self._lock:
            self._latest_packet_data = None
            self._latest_faces = []
            self._last_applied_faces = []
            self._last_face_count = 0
            self._last_applied_face_count = 0
            self._last_packet_time = 0.0
            self._last_sent_at = ""
            self._packet_revision += 1

    def start(self, host=None, port=None, settings=None):
        self.refresh_backend()
        backend_service = get_face_cap_backend_service()
        if settings is None:
            settings = _get_scene_settings()

        if host is None or port is None:
            host, port = self._resolve_host_port(settings)

        self.stop()
        self.refresh_local_ipv4(host)

        if not self._native_receiver_enabled:
            self.set_error(backend_service.get_lock_reason())
            return

        self._native_host = host
        self._native_port = port
        try:
            start_receiver = self._runtime_bindings.get("start_receiver")
            if callable(start_receiver):
                start_receiver(host, int(port), {"drop_old_packets": True})
        except Exception as exc:
            self.set_error(f"Face Capture native receiver failed on ws://{host}:{port}: {exc}")
            return

        with self._lock:
            self._native_is_listening = True
            self._native_bind_failed = False
            self._client_address = ""
            self._status_message = f"Listening on ws://{host}:{int(port)}"
            self._last_error = ""
            self._transport_mode = "websocket"
            self._transport_encoding = None
        return

    def restart(self, host=None, port=None):
        self.start(host, port)

    def _stop_receiver(self, runtime_bindings=None):
        bindings = runtime_bindings if runtime_bindings is not None else self._runtime_bindings
        try:
            stop_receiver = bindings.get("stop_receiver") if isinstance(bindings, dict) else None
            if callable(stop_receiver):
                stop_receiver()
        except Exception:
            pass

    def stop(self):
        self._stop_receiver()

        with self._lock:
            self._client_address = ""
            self._local_ipv4_address = ""
            if self._status_message != "Stopped":
                self._status_message = "Stopped"
            self._transport_mode = "websocket"
            self._transport_encoding = None
            self._native_host = ""
            self._native_port = 0
            self._native_is_listening = False
            self._native_bind_failed = False

    def _resolve_host_port(self, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if settings is None:
            return "127.0.0.1", FACE_CAP_WEBSOCKET_DEFAULT_PORT

        host = (settings.listen_host or "127.0.0.1").strip()
        port = int(settings.listen_port or FACE_CAP_WEBSOCKET_DEFAULT_PORT)
        return host, port

    def refresh_local_ipv4(self, preferred_host=""):
        discover_local_ipv4 = self._runtime_bindings.get("discover_local_ipv4")
        local_ipv4 = discover_local_ipv4(preferred_host) if callable(discover_local_ipv4) else ""
        with self._lock:
            self._local_ipv4_address = local_ipv4
        return local_ipv4

    def ingest_packet_data(self, packet_data, transport_encoding="json"):
        if packet_data is None:
            return

        now = time.time()

        with self._lock:
            if self._packet_revision != self._applied_revision and self._latest_packet_data:
                self._dropped_packet_count += 1
            self._latest_packet_data = {
                "faces": [
                    {
                        "blendshapes": dict(face.get("blendshapes", {})),
                        "head_quaternion": face.get("head_quaternion"),
                    }
                    for face in packet_data.get("faces", [])
                ],
                "face_count": max(0, int(packet_data.get("face_count", 0))),
                "sent_at": str(packet_data.get("sent_at", "")),
            }
            self._packet_count += 1
            self._packet_revision += 1
            self._last_packet_time = now
            self._last_error = ""
            self._transport_mode = "websocket"
            self._transport_encoding = transport_encoding or self._transport_encoding
            if transport_encoding == "binary":
                self._status_message = "Receiving binary blendshape packets"
            else:
                self._status_message = "Receiving JSON blendshape packets"

    def request_reapply(self):
        with self._lock:
            if self._latest_packet_data is None:
                return
            self._last_applied_face_count = -1
            self._last_applied_faces = None
            self._packet_revision += 1

    def set_error(self, message):
        with self._lock:
            self._last_error = message
            self._status_message = message

    def count_enabled_rigs(self):
        return sum(1 for _face_index, _obj, _bone in _iter_face_cap_targets())

    def apply_latest_data(self):
        with self._lock:
            packet_revision = self._packet_revision
            applied_revision = self._applied_revision
            packet_count = self._packet_count
            packet_data = self._latest_packet_data

        if packet_count <= 0:
            return
        if packet_revision == applied_revision:
            return
        if not packet_data:
            return

        faces_payload = [
            {
                "blendshapes": dict(face.get("blendshapes", {})),
                "head_quaternion": face.get("head_quaternion"),
            }
            for face in packet_data.get("faces", [])
        ]
        face_count = max(0, int(packet_data.get("face_count", 0)))
        sent_at = str(packet_data.get("sent_at", ""))
        with self._lock:
            face_payloads_equal = self._runtime_bindings.get("face_payloads_equal")
            if (
                self._last_applied_face_count == face_count
                and callable(face_payloads_equal)
                and face_payloads_equal(self._last_applied_faces, faces_payload)
            ):
                self._latest_faces = list(faces_payload)
                self._last_face_count = face_count
                self._last_sent_at = sent_at
                self._applied_revision = packet_revision
                self._applied_packet_count += 1
                return

        neutralize = face_count <= 0
        changed_objects = []
        quaternions_close = self._runtime_bindings.get("quaternions_close")

        for binding_face_index, obj, face_bone in _iter_face_cap_targets():
            face_payload = (
                faces_payload[binding_face_index]
                if 0 <= binding_face_index < len(faces_payload)
                else None
            )
            blendshapes = dict(face_payload.get("blendshapes", {})) if face_payload else {}
            raw_head_quaternion = (
                (1.0, 0.0, 0.0, 0.0)
                if neutralize
                else (face_payload.get("head_quaternion") if face_payload else None)
            )
            changed = False
            for prop_name in _get_target_props(face_bone):
                target_value = 0.0 if neutralize else blendshapes.get(prop_name, 0.0)
                current_value = float(face_bone.get(prop_name, 0.0))
                if abs(current_value - target_value) > 1e-6:
                    face_bone[prop_name] = target_value
                    changed = True

            target_head_quaternion = raw_head_quaternion or (1.0, 0.0, 0.0, 0.0)
            if target_head_quaternion is not None:
                head_bone = _get_face_blendshape_bone(obj)
                if head_bone:
                    current_quaternion = tuple(float(value) for value in head_bone.rotation_quaternion)
                    if not callable(quaternions_close) or not quaternions_close(
                        current_quaternion, target_head_quaternion
                    ):
                        head_bone.rotation_mode = "QUATERNION"
                        head_bone.rotation_quaternion = target_head_quaternion
                        changed = True

            if changed:
                changed_objects.append(obj)

        if changed_objects:
            refresh_rig_driver_batch(changed_objects, context=bpy.context, redraw=True)

        with self._lock:
            self._latest_faces = list(faces_payload)
            self._last_face_count = face_count
            self._last_sent_at = sent_at
            self._last_applied_faces = list(faces_payload)
            self._last_applied_face_count = face_count
            self._applied_revision = packet_revision
            self._applied_packet_count += 1

    def _timer_callback(self):
        try:
            if self._native_receiver_enabled:
                self._poll_native_packet()
            self.apply_latest_data()
        except Exception as exc:
            self.set_error(f"Face Capture timer error: {exc}")

        return FACE_CAP_TIMER_INTERVAL

    def _get_native_stats(self):
        if not self._native_receiver_enabled:
            return None
        try:
            get_receiver_stats = self._runtime_bindings.get("get_receiver_stats")
            stats = get_receiver_stats() if callable(get_receiver_stats) else None
        except Exception:
            return None
        return stats if isinstance(stats, dict) else None

    def _apply_native_stats(self, stats):
        if not isinstance(stats, dict):
            return
        with self._lock:
            self._native_host = str(stats.get("host", "") or "")
            self._native_port = int(stats.get("port", 0) or 0)
            self._native_is_listening = bool(stats.get("is_listening", False))
            self._native_bind_failed = bool(stats.get("bind_failed", False))
            self._client_address = str(stats.get("client_address", "") or "")
            self._packet_count = int(stats.get("packet_count", self._packet_count) or 0)
            self._dropped_packet_count = int(
                stats.get("dropped_packet_count", self._dropped_packet_count) or 0
            )
            self._last_packet_time = float(stats.get("last_packet_time", self._last_packet_time) or 0.0)
            self._last_sent_at = str(stats.get("last_sent_at", self._last_sent_at) or "")
            self._status_message = str(stats.get("status_message", self._status_message) or "")
            self._last_error = str(stats.get("last_error", self._last_error) or "")
            self._transport_mode = str(stats.get("transport_mode", "websocket") or "websocket")
            encoding = stats.get("transport_encoding", self._transport_encoding)
            self._transport_encoding = encoding if encoding else None

    def _poll_native_packet(self):
        packet = None
        transport_encoding = None
        try:
            poll_latest_packet = self._runtime_bindings.get("poll_latest_packet")
            polled = poll_latest_packet() if callable(poll_latest_packet) else None
            if isinstance(polled, dict):
                packet = polled.get("packet")
                transport_encoding = polled.get("transport_encoding")
        except Exception as exc:
            self.set_error(f"Native Face Capture receiver error: {exc}")
            return

        if packet is not None:
            self.ingest_packet_data(packet, transport_encoding=transport_encoding or "json")

    def refresh_backend(self):
        backend_service = get_face_cap_backend_service()
        previous_bindings = self._runtime_bindings
        was_native_receiver_enabled = self._native_receiver_enabled
        new_runtime_bindings = backend_service.get_runtime_bindings()
        new_native_receiver_enabled = backend_service.is_feature_unlocked() and all(
            callable(new_runtime_bindings.get(name))
            for name in ("start_receiver", "stop_receiver", "poll_latest_packet", "get_receiver_stats")
        )
        if was_native_receiver_enabled and not new_native_receiver_enabled:
            self._stop_receiver(previous_bindings)
        self._runtime_bindings = new_runtime_bindings
        self._native_receiver_enabled = new_native_receiver_enabled
        if not self._native_receiver_enabled and (
            self._native_is_listening or self._native_host or self._native_port
        ):
            with self._lock:
                self._client_address = ""
                self._local_ipv4_address = ""
                self._status_message = "Stopped"
                self._transport_mode = "websocket"
                self._transport_encoding = None
                self._native_host = ""
                self._native_port = 0
                self._native_is_listening = False
                self._native_bind_failed = False


_runtime_service = FaceCapRuntimeService()


@persistent
def _face_cap_load_post(_dummy):
    _runtime_service._ensure_timer()


def get_runtime_service():
    return _runtime_service


def register():
    handlers = bpy.app.handlers.load_post
    if _face_cap_load_post not in handlers:
        handlers.append(_face_cap_load_post)
    _runtime_service.register()


def unregister():
    handlers = bpy.app.handlers.load_post
    if _face_cap_load_post in handlers:
        handlers.remove(_face_cap_load_post)
    _runtime_service.unregister()
