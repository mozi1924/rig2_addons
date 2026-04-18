import base64
import hashlib
import json
import re
import select
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
JSON_SUBPROTOCOL = "r2fmc.json.v1"
BINARY_SUBPROTOCOL = "r2fmc.bin.v1"
BINARY_PACKET_MAGIC = 0x5232464D
BINARY_PACKET_VERSION = 1
BINARY_MESSAGE_BLENDSHAPES = 1
FACE_FLAG_HEAD_POSE = 1 << 0
FACE_FLAG_TRANSFORMATION_MATRIX = 1 << 1
HEAD_POSE_FLOAT_COUNT = 7
TRANSFORMATION_MATRIX_FLOAT_COUNT = 16
FACE_CAP_TIMER_INTERVAL = 1.0 / 60.0
FACE_CAP_DRAIN_CHUNK_SIZE = 65536
FACE_CAP_TYPE_PATTERN = re.compile(r'"type"\s*:\s*"([^"]+)"')
FACE_CAP_WEBSOCKET_DEFAULT_PORT = 9000


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _sniff_packet_type(raw_message):
    if not isinstance(raw_message, str):
        return None

    match = FACE_CAP_TYPE_PATTERN.search(raw_message[:256])
    if not match:
        return None

    return match.group(1)


def _resolve_transport_encoding(protocol):
    if protocol == BINARY_SUBPROTOCOL:
        return "binary"
    if protocol == JSON_SUBPROTOCOL:
        return "json"
    return None


def _sanitize_packet_payload(packet):
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

    sent_at = packet.get("sentAt", "")
    if sent_at is None:
        sent_at = ""

    return {
        "blendshapes": sanitized,
        "face_count": max(0, face_count),
        "sent_at": str(sent_at),
    }


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
        self._timer_registered = False
        self._latest_packet_data = None
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
        self._transport_encoding = None

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
                "is_listening": bool(
                    self._server and self._server.is_alive() and not self._server.bind_failed
                ),
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
                "transport_encoding": self._transport_encoding,
            }

    def clear_cached_packet(self):
        with self._lock:
            self._latest_packet_data = None
            self._latest_blendshapes = {}
            self._last_applied_blendshapes = {}
            self._last_face_count = 0
            self._last_applied_face_count = 0
            self._last_packet_time = 0.0
            self._last_sent_at = ""
            self._packet_revision += 1

    def is_running(self):
        return bool(self._server and self._server.is_alive() and not self._server.bind_failed)

    def start(self, host=None, port=None, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if host is None or port is None:
            host, port = self._resolve_host_port(settings)

        self.stop()

        self._server = FaceCapWebSocketServer(self, host, port)
        self._server.start()

    def restart(self, host=None, port=None):
        self.start(host, port)

    def stop(self):
        server = self._server
        self._server = None

        if server:
            server.stop()

        with self._lock:
            self._client_address = ""
            if self._status_message != "Stopped":
                self._status_message = "Stopped"
            self._transport_mode = "websocket"
            self._transport_encoding = None

    def _resolve_host_port(self, settings=None):
        if settings is None:
            settings = _get_scene_settings()

        if settings is None:
            return "127.0.0.1", FACE_CAP_WEBSOCKET_DEFAULT_PORT

        host = (settings.listen_host or "127.0.0.1").strip()
        port = int(settings.listen_port or FACE_CAP_WEBSOCKET_DEFAULT_PORT)
        return host, port

    def ingest_json_message(self, raw_message):
        packet_type = _sniff_packet_type(raw_message)
        if packet_type == "blendshapes":
            self.ingest_packet_text(raw_message)

        return None

    def ingest_packet_text(self, raw_message):
        packet_data = self._parse_packet_text(raw_message)
        if packet_data is None:
            self.note_invalid_packet("Ignored an invalid JSON blendshape packet.")
            return

        self.ingest_packet_data(packet_data, transport_encoding="json")

    def ingest_packet_data(self, packet_data, transport_encoding="json"):
        if packet_data is None:
            return

        now = time.time()

        with self._lock:
            if self._packet_revision != self._applied_revision and self._latest_packet_data:
                self._dropped_packet_count += 1
            self._latest_packet_data = {
                "blendshapes": dict(packet_data.get("blendshapes", {})),
                "face_count": max(0, int(packet_data.get("face_count", 0))),
                "sent_at": str(packet_data.get("sent_at", "")),
            }
            self._packet_count += 1
            self._packet_revision += 1
            self._last_packet_time = now
            self._last_error = ""
            self._transport_mode = "websocket"
            self._transport_encoding = transport_encoding or self._transport_encoding
            if self._server and self._server.is_alive():
                if transport_encoding == "binary":
                    self._status_message = "Receiving binary blendshape packets"
                else:
                    self._status_message = "Receiving JSON blendshape packets"

    def note_dropped_packets(self, dropped_count):
        if dropped_count <= 0:
            return

        with self._lock:
            self._dropped_packet_count += int(dropped_count)

    def note_invalid_packet(self, message):
        with self._lock:
            self._last_error = message
            if self._server and self._server.is_alive():
                self._status_message = message

    def _parse_packet_text(self, packet_text):
        try:
            packet = json.loads(packet_text)
        except json.JSONDecodeError:
            return None

        return _sanitize_packet_payload(packet)

    def parse_schema_message(self, raw_message):
        try:
            packet = json.loads(raw_message)
        except json.JSONDecodeError:
            return None

        if not isinstance(packet, dict):
            return None
        if packet.get("type") != "schema":
            return None
        if packet.get("format") != BINARY_SUBPROTOCOL:
            return None

        blendshape_names = packet.get("blendshapeNames")
        if not isinstance(blendshape_names, list):
            return []

        sanitized_names = []
        for name in blendshape_names:
            if not isinstance(name, str):
                continue
            sanitized_names.append(name)

        return sanitized_names

    def parse_binary_packet(self, packet_bytes, schema_names):
        if len(packet_bytes) < 24:
            return None

        try:
            magic = struct.unpack_from("<I", packet_bytes, 0)[0]
            version = packet_bytes[4]
            message_type = packet_bytes[5]
            frame_timestamp_ms = struct.unpack_from("<I", packet_bytes, 8)[0]
            face_count = struct.unpack_from("<H", packet_bytes, 20)[0]
        except (IndexError, struct.error):
            return None

        if magic != BINARY_PACKET_MAGIC:
            return None
        if version != BINARY_PACKET_VERSION:
            return None
        if message_type != BINARY_MESSAGE_BLENDSHAPES:
            return None

        offset = 24
        first_face_blendshapes = {}

        for face_index in range(face_count):
            if len(packet_bytes) - offset < 8:
                return None

            try:
                blendshape_count = struct.unpack_from("<H", packet_bytes, offset + 2)[0]
            except struct.error:
                return None

            flags = packet_bytes[offset + 4]
            offset += 8

            if blendshape_count > len(schema_names):
                return None

            if flags & FACE_FLAG_HEAD_POSE:
                head_pose_bytes = HEAD_POSE_FLOAT_COUNT * 4
                if len(packet_bytes) - offset < head_pose_bytes:
                    return None
                offset += head_pose_bytes

            if flags & FACE_FLAG_TRANSFORMATION_MATRIX:
                matrix_bytes = TRANSFORMATION_MATRIX_FLOAT_COUNT * 4
                if len(packet_bytes) - offset < matrix_bytes:
                    return None
                offset += matrix_bytes

            blendshape_bytes = blendshape_count * 4
            if len(packet_bytes) - offset < blendshape_bytes:
                return None

            if face_index == 0:
                face_blendshapes = {}
                for blendshape_index in range(blendshape_count):
                    try:
                        value = struct.unpack_from("<f", packet_bytes, offset)[0]
                    except struct.error:
                        return None
                    offset += 4
                    face_blendshapes[schema_names[blendshape_index]] = _clamp01(value)
                first_face_blendshapes = face_blendshapes
            else:
                offset += blendshape_bytes

        return {
            "blendshapes": first_face_blendshapes,
            "face_count": max(0, face_count),
            "sent_at": str(frame_timestamp_ms),
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
                self._transport_encoding = None
            if self._server and self._server.is_alive() and not self._server.bind_failed:
                self._status_message = f"Listening on ws://{self._server.host}:{self._server.port}"

    def set_transport_encoding(self, transport_encoding):
        with self._lock:
            self._transport_encoding = transport_encoding

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
            packet_data = self._latest_packet_data

        if packet_count <= 0:
            return
        if packet_revision == applied_revision:
            return
        if not packet_data:
            return

        blendshapes = dict(packet_data.get("blendshapes", {}))
        face_count = max(0, int(packet_data.get("face_count", 0)))
        sent_at = str(packet_data.get("sent_at", ""))

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
            self.apply_latest_data()
        except Exception as exc:
            self.set_error(f"Face Capture timer error: {exc}")

        return FACE_CAP_TIMER_INTERVAL


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
        transport_protocol = self._perform_handshake(client_socket, buffer)
        transport_encoding = _resolve_transport_encoding(transport_protocol)

        address_text = f"{address[0]}:{address[1]}"
        self.service.set_client_connected(address_text)
        if transport_encoding:
            self.service.set_transport_encoding(transport_encoding)

        schema_names = []

        try:
            while not self._stop_event.is_set():
                frames = self._recv_frame_batch(client_socket, buffer)
                should_close = False
                latest_packet_data = None
                latest_packet_encoding = transport_encoding or "json"
                dropped_blendshape_count = 0

                for opcode, payload in frames:
                    if opcode == 0x8:
                        self._send_close(client_socket)
                        should_close = True
                        break

                    if opcode == 0x9:
                        self._send_frame(client_socket, payload, opcode=0xA)
                        continue

                    if opcode == 0x1:
                        raw_message = payload.decode("utf-8", errors="replace")
                        packet_type = _sniff_packet_type(raw_message)
                        if packet_type == "schema":
                            next_schema_names = self.service.parse_schema_message(raw_message)
                            if next_schema_names is not None:
                                schema_names = next_schema_names
                                transport_encoding = "binary"
                                self.service.set_transport_encoding(transport_encoding)
                            continue

                        if packet_type != "blendshapes":
                            response = self.service.ingest_json_message(raw_message)
                            if response:
                                self._send_text(client_socket, json.dumps(response))
                            continue

                        parsed_packet = self.service._parse_packet_text(raw_message)
                        if parsed_packet is None:
                            self.service.note_invalid_packet(
                                "Ignored an invalid JSON blendshape packet."
                            )
                            continue
                        if latest_packet_data is not None:
                            dropped_blendshape_count += 1
                        latest_packet_data = parsed_packet
                        latest_packet_encoding = "json"
                        continue

                    if opcode == 0x2:
                        parsed_packet = self.service.parse_binary_packet(payload, schema_names)
                        if parsed_packet is None:
                            self.service.note_invalid_packet(
                                "Ignored an invalid binary blendshape packet."
                            )
                            continue
                        if latest_packet_data is not None:
                            dropped_blendshape_count += 1
                        latest_packet_data = parsed_packet
                        latest_packet_encoding = "binary"
                        continue

                if should_close:
                    break

                self.service.note_dropped_packets(dropped_blendshape_count)
                if latest_packet_data is not None:
                    self.service.ingest_packet_data(latest_packet_data, latest_packet_encoding)
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

        requested_protocols = []
        protocol_header = headers.get("sec-websocket-protocol", "")
        if protocol_header:
            requested_protocols = [item.strip() for item in protocol_header.split(",") if item.strip()]

        selected_protocol = ""
        if BINARY_SUBPROTOCOL in requested_protocols:
            selected_protocol = BINARY_SUBPROTOCOL
        elif JSON_SUBPROTOCOL in requested_protocols:
            selected_protocol = JSON_SUBPROTOCOL

        accept = base64.b64encode(
            hashlib.sha1((websocket_key + WEBSOCKET_MAGIC).encode("utf-8")).digest()
        ).decode("ascii")

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
        )
        if selected_protocol:
            response += f"Sec-WebSocket-Protocol: {selected_protocol}\r\n"
        response += "\r\n"
        client_socket.sendall(response.encode("utf-8"))
        return selected_protocol

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
