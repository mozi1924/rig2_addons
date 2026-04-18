import base64
import hashlib
import importlib
import importlib.util
import json
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import quote

import bpy
from bpy.app.handlers import persistent

from ...core.utils import is_rig2_armature
from .props import get_face_cap_settings
from .webtransport_helper import FaceCapWebTransportServer, parse_args as parse_webtransport_args

INTERNAL_KEYS = {"_RNA_UI", "is_rig2"}
WEBSOCKET_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
FACE_CAP_TIMER_INTERVAL = 1.0 / 60.0
FACE_CAP_DRAIN_CHUNK_SIZE = 65536
FACE_CAP_TYPE_PATTERN = re.compile(r'"type"\s*:\s*"([^"]+)"')
FACE_CAP_WEBSOCKET_DEFAULT_PORT = 9000
FACE_CAP_WEBTRANSPORT_DEFAULT_HOST = "127.0.0.1"
FACE_CAP_WEBTRANSPORT_DEFAULT_PORT = 9443
FACE_CAP_WEBTRANSPORT_RUNTIME_PACKAGE = "aioquic>=1.3.0"
FACE_CAP_WEBTRANSPORT_READY_TIMEOUT = 5.0
FACE_CAP_WEBTRANSPORT_POLL_INTERVAL = 0.05
FACE_CAP_WEBTRANSPORT_CA_CERT_FILENAME = "rig2-facecap-root-ca.cert.pem"
FACE_CAP_WEBTRANSPORT_CA_CERT_DER_FILENAME = "rig2-facecap-root-ca.cert.cer"
FACE_CAP_WEBTRANSPORT_SERVER_CERT_FILENAME = "rig2-facecap-server.cert.pem"
FACE_CAP_WEBTRANSPORT_SERVER_CHAIN_FILENAME = "rig2-facecap-server.fullchain.pem"
FACE_CAP_WEBTRANSPORT_SERVER_KEY_FILENAME = "rig2-facecap-server.key.pem"
FACE_CAP_WEBTRANSPORT_DEPENDENCY_DIRNAME = "python_modules"
FACE_CAP_WEBTRANSPORT_CERT_DIRNAME = "certificates"


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _ensure_directory(path):
    os.makedirs(path, exist_ok=True)
    return path


def _get_face_cap_runtime_dir():
    try:
        config_dir = bpy.utils.user_resource(
            "CONFIG",
            path="rig2_face_cap",
            create=True,
        )
    except Exception:
        config_dir = ""

    if config_dir:
        return _ensure_directory(config_dir)

    return _ensure_directory(os.path.join(os.path.expanduser("~"), ".rig2_face_cap"))


def _get_default_webtransport_dependency_dir():
    return _ensure_directory(
        os.path.join(_get_face_cap_runtime_dir(), FACE_CAP_WEBTRANSPORT_DEPENDENCY_DIRNAME)
    )


def _get_webtransport_dependency_dir():
    return _get_default_webtransport_dependency_dir()


def _get_bundled_webtransport_cert_dir():
    return os.path.join(os.path.dirname(__file__), FACE_CAP_WEBTRANSPORT_CERT_DIRNAME)


def _get_webtransport_cert_paths():
    cert_dir = _get_bundled_webtransport_cert_dir()
    return {
        "directory": cert_dir,
        "ca_cert": os.path.join(cert_dir, FACE_CAP_WEBTRANSPORT_CA_CERT_FILENAME),
        "ca_cert_der": os.path.join(cert_dir, FACE_CAP_WEBTRANSPORT_CA_CERT_DER_FILENAME),
        "server_cert": os.path.join(cert_dir, FACE_CAP_WEBTRANSPORT_SERVER_CERT_FILENAME),
        "server_chain": os.path.join(cert_dir, FACE_CAP_WEBTRANSPORT_SERVER_CHAIN_FILENAME),
        "server_key": os.path.join(cert_dir, FACE_CAP_WEBTRANSPORT_SERVER_KEY_FILENAME),
    }


def _ensure_webtransport_dependency_path():
    dependency_dir = _get_webtransport_dependency_dir()
    if dependency_dir not in sys.path:
        sys.path.insert(0, dependency_dir)
    importlib.invalidate_caches()
    return dependency_dir


def _purge_webtransport_modules():
    for module_name in list(sys.modules.keys()):
        if module_name == "aioquic" or module_name.startswith("aioquic."):
            sys.modules.pop(module_name, None)


def _get_webtransport_dependency_details():
    _ensure_webtransport_dependency_path()
    try:
        spec = importlib.util.find_spec("aioquic")
    except Exception:
        spec = None

    if spec is None:
        return {
            "available": False,
            "origin": "",
        }

    return {
        "available": True,
        "origin": str(getattr(spec, "origin", "") or ""),
    }


def get_webtransport_dependency_dir():
    return _get_webtransport_dependency_dir()


def _sniff_packet_type(raw_message):
    if not isinstance(raw_message, str):
        return None

    match = FACE_CAP_TYPE_PATTERN.search(raw_message[:256])
    if not match:
        return None

    return match.group(1)


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


def _get_target_rig():
    settings = _get_scene_settings()
    if settings is None:
        return None

    obj = getattr(settings, "target_rig", None)
    if obj and is_rig2_armature(obj):
        return obj

    return None


def _iter_face_cap_targets():
    obj = _get_target_rig()
    if obj and _is_face_cap_enabled(obj):
        yield obj, obj.pose.bones["Face_BlendShapes"]


def _get_target_props(face_bone):
    return [key for key in face_bone.keys() if key not in INTERNAL_KEYS]


class FaceCapRuntimeService:
    def __init__(self):
        self._lock = threading.Lock()
        self._server = None
        self._udp_bridge = None
        self._webtransport_server = None
        self._webtransport_ready_event = threading.Event()
        self._timer_registered = False
        self._latest_packet_text = None
        self._latest_blendshapes = {}
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
        self._last_applied_blendshapes = {}
        self._last_applied_face_count = 0
        self._transport_mode = "websocket"
        self._webtransport_status = "Stopped"
        self._webtransport_url = ""
        self._webtransport_last_error = ""
        self._webtransport_dependency_ready = False
        self._webtransport_cert_ready = False

    def register(self):
        self._ensure_timer()

    def unregister(self):
        if self._timer_registered:
            try:
                bpy.app.timers.unregister(self._timer_callback)
            except Exception:
                pass
            self._timer_registered = False

        self.stop()

    def _ensure_timer(self):
        if self._timer_registered:
            return

        bpy.app.timers.register(self._timer_callback, first_interval=0.1, persistent=True)
        self._timer_registered = True

    def get_status_snapshot(self):
        dependency_details = _get_webtransport_dependency_details()
        cert_paths = _get_webtransport_cert_paths()
        with self._lock:
            if self._last_packet_time > 0.0:
                age_seconds = max(0.0, time.time() - self._last_packet_time)
            else:
                age_seconds = None

            return {
                "host": self._server.host if self._server else "",
                "port": self._server.port if self._server else 0,
                "is_listening": bool(self._server and self._server.is_alive() and not self._server.bind_failed),
                "bind_failed": bool(self._server and self._server.bind_failed),
                "client_address": self._client_address,
                "packet_count": self._packet_count,
                "dropped_packet_count": self._dropped_packet_count,
                "applied_packet_count": self._applied_packet_count,
                "face_count": self._last_face_count,
                "last_sent_at": self._last_sent_at,
                "last_packet_age": age_seconds,
                "status_message": self._status_message,
                "last_error": self._last_error,
                "target_name": _get_target_rig().name if _get_target_rig() else "",
                "transport_mode": self._transport_mode,
                "webtransport_status": self._webtransport_status,
                "webtransport_url": self._webtransport_url,
                "webtransport_last_error": self._webtransport_last_error,
                "webtransport_dependency_ready": dependency_details["available"],
                "webtransport_cert_ready": all(
                    os.path.isfile(cert_paths[key])
                    for key in ("ca_cert", "ca_cert_der", "server_chain", "server_key")
                ),
                "webtransport_dependency_origin": dependency_details["origin"],
                "webtransport_dependency_dir": _get_webtransport_dependency_dir(),
                "webtransport_ca_cert_path": cert_paths["ca_cert"],
                "webtransport_ca_cert_der_path": cert_paths["ca_cert_der"],
                "webtransport_server_cert_path": cert_paths["server_chain"],
                "webtransport_server_key_path": cert_paths["server_key"],
            }

    def clear_cached_packet(self):
        with self._lock:
            self._latest_packet_text = None
            self._latest_blendshapes = {}
            self._last_applied_blendshapes = {}
            self._last_face_count = 0
            self._last_applied_face_count = 0
            self._last_packet_time = 0.0
            self._last_sent_at = ""
            self._packet_revision += 1
            self._transport_mode = "websocket"

    def is_running(self):
        return bool(self._server and self._server.is_alive() and not self._server.bind_failed)

    def is_webtransport_running(self):
        server = self._webtransport_server
        return bool(server and server.is_alive() and self._webtransport_ready_event.is_set())

    def install_webtransport_dependency(self):
        dependency_dir = _ensure_directory(_get_webtransport_dependency_dir())

        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--target",
                dependency_dir,
                "--upgrade",
                FACE_CAP_WEBTRANSPORT_RUNTIME_PACKAGE,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        _purge_webtransport_modules()
        dependency_details = _get_webtransport_dependency_details()
        with self._lock:
            self._webtransport_dependency_ready = dependency_details["available"]
            self._webtransport_last_error = ""

        return dependency_dir

    def uninstall_webtransport_dependency(self):
        dependency_dir = _get_webtransport_dependency_dir()
        if os.path.isdir(dependency_dir):
            shutil.rmtree(dependency_dir, ignore_errors=True)
        _ensure_directory(dependency_dir)
        _purge_webtransport_modules()

        dependency_details = _get_webtransport_dependency_details()
        with self._lock:
            self._webtransport_dependency_ready = dependency_details["available"]
            if not dependency_details["available"]:
                self._webtransport_status = "WebSocket only"
            self._webtransport_last_error = ""

        return dependency_dir

    def ensure_webtransport_runtime(self, settings=None):
        return self.install_webtransport_dependency()

    def ensure_webtransport_certificates(self, settings=None):
        cert_paths = _get_webtransport_cert_paths()
        required_paths = (
            cert_paths["ca_cert"],
            cert_paths["ca_cert_der"],
            cert_paths["server_cert"],
            cert_paths["server_chain"],
            cert_paths["server_key"],
        )
        if not all(os.path.isfile(path) for path in required_paths):
            raise RuntimeError("Bundled WebTransport certificates are missing from the addon package.")

        with self._lock:
            self._webtransport_cert_ready = True
            self._webtransport_last_error = ""

        return cert_paths

    def _mark_webtransport_error(self, message):
        with self._lock:
            self._webtransport_last_error = message
            self._webtransport_status = message
            self._webtransport_ready_event.clear()

    def handle_webtransport_process_output(self, line):
        if not line:
            return

        if line.startswith("WT_READY "):
            with self._lock:
                self._webtransport_status = line[len("WT_READY "):]
                self._webtransport_last_error = ""
                self._webtransport_ready_event.set()
            return

        if line.startswith("WT_INFO "):
            with self._lock:
                self._webtransport_status = line[len("WT_INFO "):]
            return

        if line.startswith("WT_ERROR "):
            self._mark_webtransport_error(line[len("WT_ERROR "):])

    def start(self, host=None, port=None, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if host is None or port is None:
            host, port = self._resolve_host_port(settings)

        self.stop()

        self._server = FaceCapWebSocketServer(self, host, port)
        self._server.start()

        self._start_webtransport(settings)

    def restart(self, host=None, port=None):
        self.start(host, port)

    def stop(self):
        server = self._server
        self._server = None

        self._stop_webtransport()

        if server:
            server.stop()

        with self._lock:
            self._client_address = ""
            if self._status_message != "Stopped":
                self._status_message = "Stopped"
            self._transport_mode = "websocket"

    def _resolve_host_port(self, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if settings is None:
            return "127.0.0.1", FACE_CAP_WEBSOCKET_DEFAULT_PORT

        host = (settings.listen_host or "127.0.0.1").strip()
        port = int(settings.listen_port or FACE_CAP_WEBSOCKET_DEFAULT_PORT)
        return host, port

    def _resolve_webtransport_host_port(self, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if settings is None:
            return FACE_CAP_WEBTRANSPORT_DEFAULT_HOST, FACE_CAP_WEBTRANSPORT_DEFAULT_PORT

        host = (
            getattr(settings, "webtransport_host", FACE_CAP_WEBTRANSPORT_DEFAULT_HOST)
            or FACE_CAP_WEBTRANSPORT_DEFAULT_HOST
        ).strip()
        if host not in {"127.0.0.1", "localhost"}:
            host = FACE_CAP_WEBTRANSPORT_DEFAULT_HOST
        port = int(
            getattr(settings, "webtransport_port", FACE_CAP_WEBTRANSPORT_DEFAULT_PORT)
            or FACE_CAP_WEBTRANSPORT_DEFAULT_PORT
        )
        return host, port

    def _start_webtransport(self, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        enabled = bool(getattr(settings, "webtransport_enabled", True)) if settings else True
        dependency_details = _get_webtransport_dependency_details()
        cert_paths = _get_webtransport_cert_paths()
        cert_ready = all(
            os.path.isfile(cert_paths[key])
            for key in ("ca_cert", "ca_cert_der", "server_chain", "server_key")
        )

        if not enabled:
            with self._lock:
                self._webtransport_status = "Disabled"
                self._webtransport_last_error = ""
                self._webtransport_url = ""
                self._webtransport_dependency_ready = dependency_details["available"]
                self._webtransport_cert_ready = cert_ready
            return

        with self._lock:
            self._webtransport_dependency_ready = dependency_details["available"]
            self._webtransport_cert_ready = cert_ready

        if not dependency_details["available"]:
            with self._lock:
                self._webtransport_status = "WebSocket only (WT dependency missing)"
                self._webtransport_last_error = ""
                self._webtransport_url = ""
            return
        if not cert_ready:
            with self._lock:
                self._webtransport_status = "WebSocket only (bundled WT cert missing)"
                self._webtransport_last_error = ""
                self._webtransport_url = ""
            return

        udp_bridge = FaceCapUdpBridgeServer(self)
        udp_bridge.start()
        udp_port = udp_bridge.bound_port
        if udp_port <= 0:
            udp_bridge.stop()
            self._mark_webtransport_error("Failed to start the local WebTransport UDP bridge.")
            return

        host, port = self._resolve_webtransport_host_port(settings)
        wt_server = FaceCapWebTransportServer(
            parse_webtransport_args(
                [
                    "--host",
                    host,
                    "--port",
                    str(port),
                    "--udp-host",
                    "127.0.0.1",
                    "--udp-port",
                    str(udp_port),
                    "--cert",
                    cert_paths["server_chain"],
                    "--key",
                    cert_paths["server_key"],
                ]
            ),
            emit=self.handle_webtransport_process_output,
        )
        wt_server.start()
        wt_server.wait_started(timeout=1.0)

        self._udp_bridge = udp_bridge
        self._webtransport_server = wt_server
        self._webtransport_ready_event.clear()
        self._webtransport_url = f"https://{host}:{port}/capture"
        with self._lock:
            self._webtransport_status = f"Starting on {self._webtransport_url}"
            self._webtransport_last_error = ""

        deadline = time.time() + FACE_CAP_WEBTRANSPORT_READY_TIMEOUT
        while time.time() < deadline:
            if self._webtransport_ready_event.wait(FACE_CAP_WEBTRANSPORT_POLL_INTERVAL):
                return
            if not wt_server.is_alive():
                break

        if not self._webtransport_ready_event.is_set():
            self._stop_webtransport()
            self._mark_webtransport_error("WebTransport server failed to start.")

    def _stop_webtransport(self):
        server = self._webtransport_server
        self._webtransport_server = None
        self._webtransport_ready_event.clear()

        if server:
            server.stop()

        udp_bridge = self._udp_bridge
        self._udp_bridge = None
        if udp_bridge:
            udp_bridge.stop()

        with self._lock:
            if self._webtransport_status != "Disabled":
                self._webtransport_status = "Stopped"
            self._webtransport_url = ""

    def ingest_json_message(self, raw_message):
        packet_type = _sniff_packet_type(raw_message)
        if packet_type == "blendshapes":
            with self._lock:
                self._transport_mode = "websocket"
            self.ingest_packet_text(raw_message)
            return None

        if packet_type not in {
            "transport.hello",
            "transport.webtransport.ready",
            "transport.webtransport.failed",
        }:
            return None

        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return None

        if not isinstance(message, dict):
            return None

        message_type = message.get("type")
        if message_type == "transport.hello":
            session_id = message.get("sessionId")
            if self.is_webtransport_running():
                with self._lock:
                    self._webtransport_status = "Negotiated over WebSocket control channel"
                return {
                    "type": "transport.webtransport.offer",
                    "version": 1,
                    "sessionId": session_id,
                    "url": f"{self._webtransport_url}?session={quote(str(session_id or ''))}",
                }

            return {
                "type": "transport.webtransport.unavailable",
                "version": 1,
                "sessionId": session_id,
                "reason": "webtransport_not_ready",
            }

        if message_type == "transport.webtransport.ready":
            with self._lock:
                self._transport_mode = "webtransport"
                self._webtransport_status = "Receiving WebTransport datagrams"
                self._webtransport_last_error = ""
                self._status_message = "Receiving WebTransport datagrams"
            return None

        if message_type == "transport.webtransport.failed":
            reason = str(message.get("reason") or "unknown_error")
            with self._lock:
                self._transport_mode = "websocket"
                self._webtransport_last_error = reason
                self._webtransport_status = f"Fallback to WebSocket ({reason})"
                if self._server and self._server.is_alive():
                    self._status_message = "Receiving blendshape packets"

        return None

    def ingest_packet_text(self, raw_message):
        now = time.time()

        with self._lock:
            if self._packet_revision != self._applied_revision and self._latest_packet_text:
                self._dropped_packet_count += 1
            self._latest_packet_text = raw_message
            self._packet_count += 1
            self._packet_revision += 1
            self._last_packet_time = now
            self._last_error = ""
            if self._server and self._server.is_alive():
                self._status_message = "Receiving blendshape packets"

    def note_dropped_packets(self, dropped_count):
        if dropped_count <= 0:
            return

        with self._lock:
            self._dropped_packet_count += int(dropped_count)

    def _parse_packet_text(self, packet_text):
        try:
            packet = json.loads(packet_text)
        except json.JSONDecodeError:
            return None

        if not isinstance(packet, dict):
            return None

        faces = packet.get("faces")
        if not isinstance(faces, list):
            faces = []

        first_face = faces[0] if faces else {}
        blendshape_payload = first_face.get("blendshapes", {}) if isinstance(first_face, dict) else {}
        if not isinstance(blendshape_payload, dict):
            blendshape_payload = {}

        sanitized = {}
        for key, value in blendshape_payload.items():
            try:
                sanitized[str(key)] = _clamp01(value)
            except Exception:
                continue

        try:
            face_count = int(packet.get("faceCount", len(faces)))
        except Exception:
            face_count = len(faces)

        return {
            "blendshapes": sanitized,
            "face_count": max(0, face_count),
            "sent_at": str(packet.get("sentAt", "")),
        }

    def set_listening(self, host, port):
        with self._lock:
            self._status_message = f"Listening on ws://{host}:{port}"
            self._last_error = ""

    def set_client_connected(self, address):
        with self._lock:
            self._client_address = address
            self._status_message = f"Client connected: {address}"
            self._last_error = ""

    def clear_client_connected(self, address):
        with self._lock:
            if self._client_address == address:
                self._client_address = ""
            if self._server and self._server.is_alive() and not self._server.bind_failed:
                self._status_message = f"Listening on ws://{self._server.host}:{self._server.port}"

    def set_error(self, message):
        with self._lock:
            self._last_error = message
            self._status_message = message

    def count_enabled_rigs(self):
        return sum(1 for _obj, _bone in _iter_face_cap_targets())

    def apply_latest_data(self):
        with self._lock:
            packet_revision = self._packet_revision
            applied_revision = self._applied_revision
            packet_count = self._packet_count
            packet_text = self._latest_packet_text

        if packet_count <= 0:
            return
        if packet_revision == applied_revision:
            return
        if not packet_text:
            return

        parsed_packet = self._parse_packet_text(packet_text)
        if parsed_packet is None:
            with self._lock:
                self._applied_revision = packet_revision
                self._applied_packet_count += 1
                self._last_error = "Ignored an invalid blendshape packet."
            return

        blendshapes = parsed_packet["blendshapes"]
        face_count = parsed_packet["face_count"]
        sent_at = parsed_packet["sent_at"]

        with self._lock:
            if (
                self._last_applied_face_count == face_count
                and self._last_applied_blendshapes == blendshapes
            ):
                self._latest_blendshapes = dict(blendshapes)
                self._last_face_count = face_count
                self._last_sent_at = sent_at
                self._applied_revision = packet_revision
                self._applied_packet_count += 1
                return

        neutralize = face_count <= 0
        changed_objects = []

        for obj, face_bone in _iter_face_cap_targets():
            changed = False
            for prop_name in _get_target_props(face_bone):
                target_value = 0.0 if neutralize else blendshapes.get(prop_name, 0.0)
                current_value = float(face_bone.get(prop_name, 0.0))
                if abs(current_value - target_value) > 1e-6:
                    face_bone[prop_name] = target_value
                    changed = True

            if changed:
                changed_objects.append(obj)

        for obj in changed_objects:
            try:
                obj.update_tag(refresh={"OBJECT", "DATA"})
            except Exception:
                pass

        if changed_objects:
            window_manager = getattr(bpy.context, "window_manager", None)
            for window in getattr(window_manager, "windows", []):
                screen = getattr(window, "screen", None)
                if not screen:
                    continue
                for area in screen.areas:
                    try:
                        area.tag_redraw()
                    except Exception:
                        pass

        with self._lock:
            self._latest_blendshapes = dict(blendshapes)
            self._last_face_count = face_count
            self._last_sent_at = sent_at
            self._last_applied_blendshapes = dict(blendshapes)
            self._last_applied_face_count = face_count
            self._applied_revision = packet_revision
            self._applied_packet_count += 1

    def _timer_callback(self):
        try:
            server = self._webtransport_server
            if server and not server.is_alive() and self._webtransport_ready_event.is_set():
                self._stop_webtransport()
                self._mark_webtransport_error("WebTransport server stopped unexpectedly.")
            self.apply_latest_data()
        except Exception as exc:
            self.set_error(f"Face Capture timer error: {exc}")

        return FACE_CAP_TIMER_INTERVAL


class FaceCapUdpBridgeServer(threading.Thread):
    def __init__(self, service):
        super().__init__(daemon=True)
        self.service = service
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._socket = None
        self.bound_port = 0

    def start(self):
        super().start()
        self._ready_event.wait(timeout=1.0)

    def stop(self):
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        if self.is_alive():
            self.join(timeout=1.0)

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.bind(("127.0.0.1", 0))
        self._socket = sock
        self.bound_port = sock.getsockname()[1]
        self._ready_event.set()

        try:
            while not self._stop_event.is_set():
                try:
                    payload, _address = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not payload:
                    continue

                self.service.ingest_packet_text(payload.decode("utf-8", errors="replace"))
                with self.service._lock:
                    self.service._transport_mode = "webtransport"
                    if not self.service._status_message.startswith("Face Capture timer error"):
                        self.service._status_message = "Receiving WebTransport datagrams"
        finally:
            try:
                sock.close()
            except OSError:
                pass


class FaceCapWebSocketServer(threading.Thread):
    def __init__(self, service, host, port):
        super().__init__(daemon=True)
        self.service = service
        self.host = host
        self.port = port
        self.bind_failed = False
        self._stop_event = threading.Event()
        self._server_socket = None
        self._client_socket = None

    def matches(self, host, port):
        return self.host == host and self.port == port

    def stop(self):
        self._stop_event.set()

        for sock in (self._client_socket, self._server_socket):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass

        if self.is_alive():
            self.join(timeout=1.0)

    def run(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            except OSError:
                pass
            server_socket.bind((self.host, self.port))
            server_socket.listen(8)
            server_socket.settimeout(0.5)
            self._server_socket = server_socket
            self.service.set_listening(self.host, self.port)
        except OSError as exc:
            self.bind_failed = True
            self.service.set_error(f"Face Capture receiver failed on ws://{self.host}:{self.port}: {exc}")
            return

        with self._server_socket:
            while not self._stop_event.is_set():
                try:
                    client_socket, address = self._server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                self._client_socket = client_socket
                try:
                    self._handle_client(client_socket, address)
                except Exception as exc:
                    self.service.set_error(f"Face Capture client error: {exc}")
                finally:
                    self._client_socket = None

    def _handle_client(self, client_socket, address):
        client_socket.settimeout(0.5)
        try:
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        except OSError:
            pass
        buffer = bytearray()
        self._perform_handshake(client_socket, buffer)

        address_text = f"{address[0]}:{address[1]}"
        self.service.set_client_connected(address_text)

        try:
            while not self._stop_event.is_set():
                frames = self._recv_frame_batch(client_socket, buffer)
                should_close = False
                latest_blendshape_message = None
                dropped_blendshape_count = 0

                for opcode, payload in frames:
                    if opcode == 0x8:
                        self._send_close(client_socket)
                        should_close = True
                        break

                    if opcode == 0x9:
                        self._send_frame(client_socket, payload, opcode=0xA)
                        continue

                    if opcode != 0x1:
                        continue

                    raw_message = payload.decode("utf-8", errors="replace")
                    packet_type = _sniff_packet_type(raw_message)
                    if packet_type == "blendshapes":
                        if latest_blendshape_message is not None:
                            dropped_blendshape_count += 1
                        latest_blendshape_message = raw_message
                        continue

                    response = self.service.ingest_json_message(raw_message)
                    if response:
                        self._send_text(client_socket, json.dumps(response))

                if should_close:
                    break

                self.service.note_dropped_packets(dropped_blendshape_count)
                if latest_blendshape_message is not None:
                    self.service.ingest_packet_text(latest_blendshape_message)
        finally:
            self.service.clear_client_connected(address_text)
            try:
                client_socket.close()
            except OSError:
                pass

    def _perform_handshake(self, client_socket, buffer):
        header_bytes = self._recv_until(client_socket, buffer, b"\r\n\r\n")
        request_text = header_bytes.decode("utf-8", errors="replace")
        lines = request_text.split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        websocket_key = headers.get("sec-websocket-key")
        if not websocket_key:
            raise RuntimeError("Missing Sec-WebSocket-Key")

        accept = base64.b64encode(
            hashlib.sha1((websocket_key + WEBSOCKET_MAGIC).encode("utf-8")).digest()
        ).decode("ascii")

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        client_socket.sendall(response.encode("utf-8"))

    def _recv_until(self, client_socket, buffer, marker):
        while marker not in buffer:
            chunk = client_socket.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            buffer.extend(chunk)

        end_index = buffer.index(marker) + len(marker)
        data = bytes(buffer[:end_index])
        del buffer[:end_index]
        return data

    def _recv_frame(self, client_socket, buffer):
        header = self._read_exact(client_socket, buffer, 2)
        first_byte, second_byte = header[0], header[1]
        opcode = first_byte & 0x0F
        masked = (second_byte & 0x80) != 0
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            payload_length = struct.unpack("!H", self._read_exact(client_socket, buffer, 2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack("!Q", self._read_exact(client_socket, buffer, 8))[0]

        mask = self._read_exact(client_socket, buffer, 4) if masked else b""
        payload = self._read_exact(client_socket, buffer, payload_length) if payload_length else b""

        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

        return opcode, payload

    def _recv_frame_batch(self, client_socket, buffer):
        frames = [self._recv_frame(client_socket, buffer)]
        self._drain_available_socket_bytes(client_socket, buffer)

        while True:
            frame = self._try_recv_frame_from_buffer(buffer)
            if frame is None:
                break
            frames.append(frame)

        return frames

    def _drain_available_socket_bytes(self, client_socket, buffer):
        while not self._stop_event.is_set():
            try:
                readable, _, _ = select.select([client_socket], [], [], 0.0)
            except (OSError, ValueError):
                break

            if not readable:
                break

            try:
                chunk = client_socket.recv(FACE_CAP_DRAIN_CHUNK_SIZE)
            except (BlockingIOError, InterruptedError, socket.timeout):
                break

            if not chunk:
                raise ConnectionError("Connection closed")
            buffer.extend(chunk)

    def _try_recv_frame_from_buffer(self, buffer):
        if len(buffer) < 2:
            return None

        first_byte = buffer[0]
        second_byte = buffer[1]
        opcode = first_byte & 0x0F
        masked = (second_byte & 0x80) != 0
        payload_length = second_byte & 0x7F
        header_length = 2

        if payload_length == 126:
            if len(buffer) < 4:
                return None
            payload_length = struct.unpack("!H", bytes(buffer[2:4]))[0]
            header_length = 4
        elif payload_length == 127:
            if len(buffer) < 10:
                return None
            payload_length = struct.unpack("!Q", bytes(buffer[2:10]))[0]
            header_length = 10

        mask_length = 4 if masked else 0
        frame_length = header_length + mask_length + payload_length
        if len(buffer) < frame_length:
            return None

        payload_offset = header_length
        if masked:
            mask = bytes(buffer[payload_offset:payload_offset + 4])
            payload_offset += 4
        else:
            mask = b""

        payload = bytes(buffer[payload_offset:payload_offset + payload_length])
        del buffer[:frame_length]

        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

        return opcode, payload

    def _read_exact(self, client_socket, buffer, size):
        while len(buffer) < size:
            try:
                chunk = client_socket.recv(max(4096, size - len(buffer)))
            except socket.timeout:
                if self._stop_event.is_set():
                    raise ConnectionError("Face Capture receiver stopped")
                continue

            if not chunk:
                raise ConnectionError("Connection closed")
            buffer.extend(chunk)

        data = bytes(buffer[:size])
        del buffer[:size]
        return data

    def _send_text(self, client_socket, text):
        self._send_frame(client_socket, text.encode("utf-8"), opcode=0x1)

    def _send_close(self, client_socket):
        try:
            self._send_frame(client_socket, b"", opcode=0x8)
        except OSError:
            pass

    def _send_frame(self, client_socket, payload, opcode):
        payload_length = len(payload)
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))

        if payload_length < 126:
            header.append(payload_length)
        elif payload_length <= 0xFFFF:
            header.append(126)
            header.extend(struct.pack("!H", payload_length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", payload_length))

        client_socket.sendall(bytes(header) + payload)


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
