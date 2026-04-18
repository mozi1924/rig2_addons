import base64
import hashlib
import json
import socket
import struct
import threading
import time

import bpy
from bpy.app.handlers import persistent

from ...core.utils import is_rig2_armature
from .props import get_face_cap_settings

INTERNAL_KEYS = {"_RNA_UI", "is_rig2"}
WEBSOCKET_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _is_face_cap_enabled(obj):
    if not is_rig2_armature(obj):
        return False

    pose = getattr(obj, "pose", None)
    if not pose:
        return False

    head_bone = pose.bones.get("prop.head")
    face_bone = pose.bones.get("Face_BlendShapes")
    if not head_bone or not face_bone:
        return False

    return float(head_bone.get("face_cap", 0.0)) >= 0.999


def _iter_face_cap_targets():
    for obj in bpy.data.objects:
        if _is_face_cap_enabled(obj):
            yield obj, obj.pose.bones["Face_BlendShapes"]


def _get_target_props(face_bone):
    return [key for key in face_bone.keys() if key not in INTERNAL_KEYS]


class FaceCapRuntimeService:
    def __init__(self):
        self._lock = threading.Lock()
        self._server = None
        self._timer_registered = False
        self._latest_blendshapes = {}
        self._last_face_count = 0
        self._packet_count = 0
        self._last_packet_time = 0.0
        self._last_sent_at = ""
        self._client_address = ""
        self._status_message = "Stopped"
        self._last_error = ""

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
                "face_count": self._last_face_count,
                "last_sent_at": self._last_sent_at,
                "last_packet_age": age_seconds,
                "status_message": self._status_message,
                "last_error": self._last_error,
            }

    def clear_cached_packet(self):
        with self._lock:
            self._latest_blendshapes = {}
            self._last_face_count = 0
            self._last_packet_time = 0.0
            self._last_sent_at = ""

    def ensure_running(self):
        host, port = self._resolve_host_port()

        if self._server and self._server.matches(host, port):
            if self._server.is_alive() or self._server.bind_failed:
                return

        self.restart(host, port)

    def restart(self, host=None, port=None):
        if host is None or port is None:
            host, port = self._resolve_host_port()

        self.stop()
        self._server = FaceCapWebSocketServer(self, host, port)
        self._server.start()

    def stop(self):
        server = self._server
        self._server = None

        if server:
            server.stop()

        with self._lock:
            self._client_address = ""
            if self._status_message != "Stopped":
                self._status_message = "Stopped"

    def ingest_json_message(self, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return None

        if not isinstance(message, dict):
            return None

        packet_type = message.get("type")
        if packet_type == "blendshapes":
            self.ingest_packet(message)
            return None

        if packet_type == "transport.hello":
            return {
                "type": "transport.webtransport.unavailable",
                "version": 1,
                "sessionId": message.get("sessionId"),
                "reason": "webtransport_disabled",
            }

        return None

    def ingest_packet(self, packet):
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

        with self._lock:
            self._latest_blendshapes = sanitized
            self._last_face_count = max(0, face_count)
            self._packet_count += 1
            self._last_packet_time = time.time()
            self._last_sent_at = str(packet.get("sentAt", ""))
            self._last_error = ""
            if self._server and self._server.is_alive():
                self._status_message = "Receiving blendshape packets"

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
            blendshapes = dict(self._latest_blendshapes)
            face_count = self._last_face_count
            packet_count = self._packet_count

        if packet_count <= 0:
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
            view_layer = getattr(bpy.context, "view_layer", None)
            if view_layer:
                try:
                    view_layer.update()
                except Exception:
                    pass

    def _resolve_host_port(self):
        settings = None
        scene = getattr(bpy.context, "scene", None)
        if scene:
            settings = get_face_cap_settings(scene)
        else:
            scenes = getattr(getattr(bpy, "data", None), "scenes", None)
            if scenes:
                settings = get_face_cap_settings(scenes[0])

        if settings is None:
            return "127.0.0.1", 9000

        host = (settings.listen_host or "127.0.0.1").strip()
        port = int(settings.listen_port or 9000)
        return host, port

    def _timer_callback(self):
        try:
            self.ensure_running()
            self.apply_latest_data()
        except Exception as exc:
            self.set_error(f"Face Capture timer error: {exc}")

        return 0.05


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
            server_socket.bind((self.host, self.port))
            server_socket.listen(1)
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
        buffer = bytearray()
        self._perform_handshake(client_socket, buffer)

        address_text = f"{address[0]}:{address[1]}"
        self.service.set_client_connected(address_text)

        try:
            while not self._stop_event.is_set():
                opcode, payload = self._recv_frame(client_socket, buffer)
                if opcode == 0x8:
                    self._send_close(client_socket)
                    break

                if opcode == 0x9:
                    self._send_frame(client_socket, payload, opcode=0xA)
                    continue

                if opcode != 0x1:
                    continue

                response = self.service.ingest_json_message(payload.decode("utf-8", errors="replace"))
                if response:
                    self._send_text(client_socket, json.dumps(response))
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
    _runtime_service.ensure_running()


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
