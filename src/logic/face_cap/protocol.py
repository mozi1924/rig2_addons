import ipaddress
import json
import math
import re
import socket
import struct


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
FACE_CAP_TYPE_PATTERN = re.compile(r'"type"\s*:\s*"([^"]+)"')


def clamp01(value):
    return max(0.0, min(1.0, float(value)))


def sniff_packet_type(raw_message):
    if not isinstance(raw_message, str):
        return None

    match = FACE_CAP_TYPE_PATTERN.search(raw_message[:256])
    if not match:
        return None

    return match.group(1)


def resolve_transport_encoding(protocol):
    if protocol == BINARY_SUBPROTOCOL:
        return "binary"
    if protocol == JSON_SUBPROTOCOL:
        return "json"
    return None


def normalize_ipv4_address(address):
    try:
        ip = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return ""

    if ip.version != 4:
        return ""

    return str(ip)


def is_preferred_lan_ipv4(address):
    normalized = normalize_ipv4_address(address)
    if not normalized:
        return False

    ip = ipaddress.ip_address(normalized)
    return not (ip.is_loopback or ip.is_unspecified or ip.is_link_local)


def discover_local_ipv4(preferred_host=""):
    normalized_host = normalize_ipv4_address(preferred_host)
    if is_preferred_lan_ipv4(normalized_host):
        return normalized_host

    candidates = []
    seen = set()

    def add_candidate(address):
        normalized = normalize_ipv4_address(address)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    if normalized_host and normalized_host != "0.0.0.0":
        add_candidate(normalized_host)

    probe_targets = (("192.0.2.1", 80), ("8.8.8.8", 80))
    for target_host, target_port in probe_targets:
        probe_socket = None
        try:
            probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe_socket.settimeout(0.2)
            probe_socket.connect((target_host, target_port))
            add_candidate(probe_socket.getsockname()[0])
        except OSError:
            pass
        finally:
            if probe_socket is not None:
                try:
                    probe_socket.close()
                except OSError:
                    pass

    host_names = [socket.gethostname()]
    fqdn = socket.getfqdn()
    if fqdn and fqdn not in host_names:
        host_names.append(fqdn)

    for host_name in host_names:
        try:
            for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
                host_name,
                None,
                socket.AF_INET,
                socket.SOCK_DGRAM,
            ):
                if family == socket.AF_INET and sockaddr:
                    add_candidate(sockaddr[0])
        except OSError:
            pass

        try:
            _host_name, _aliases, host_addresses = socket.gethostbyname_ex(host_name)
            for address in host_addresses:
                add_candidate(address)
        except OSError:
            pass

    for candidate in candidates:
        if is_preferred_lan_ipv4(candidate):
            return candidate

    if normalized_host and normalized_host != "0.0.0.0":
        return normalized_host

    for candidate in candidates:
        if candidate != "0.0.0.0":
            return candidate

    return ""


def sanitize_head_quaternion(quaternion_payload):
    if not isinstance(quaternion_payload, dict):
        return None

    try:
        w = float(quaternion_payload.get("w", 1.0))
        x = float(quaternion_payload.get("x", 0.0))
        y = float(quaternion_payload.get("y", 0.0))
        z = float(quaternion_payload.get("z", 0.0))
    except Exception:
        return None

    if not all(math.isfinite(value) for value in (w, x, y, z)):
        return None

    magnitude = math.sqrt((w * w) + (x * x) + (y * y) + (z * z))
    if magnitude <= 1e-8:
        return None

    return (w / magnitude, x / magnitude, y / magnitude, z / magnitude)


def sanitize_packet_payload(packet):
    if not isinstance(packet, dict):
        return None

    faces = packet.get("faces")
    if not isinstance(faces, list):
        faces = []

    try:
        face_count = int(packet.get("faceCount", len(faces)))
    except Exception:
        face_count = len(faces)

    sent_at = packet.get("sentAt", "")
    if sent_at is None:
        sent_at = ""

    sanitized_faces = []
    for face in faces:
        if not isinstance(face, dict):
            sanitized_faces.append({"blendshapes": {}, "head_quaternion": None})
            continue

        blendshape_payload = face.get("blendshapes", {})
        if not isinstance(blendshape_payload, dict):
            blendshape_payload = {}

        sanitized_blendshapes = {}
        for key, value in blendshape_payload.items():
            try:
                sanitized_blendshapes[str(key)] = clamp01(value)
            except Exception:
                continue

        head_quaternion = None
        head_pose = face.get("headPose")
        if isinstance(head_pose, dict):
            head_quaternion = sanitize_head_quaternion(head_pose.get("quaternionWxyz"))

        sanitized_faces.append(
            {
                "blendshapes": sanitized_blendshapes,
                "head_quaternion": head_quaternion,
            }
        )

    return {
        "faces": sanitized_faces,
        "face_count": max(0, face_count),
        "sent_at": str(sent_at),
    }


def quaternions_close(lhs, rhs, epsilon=1e-6):
    if lhs is None or rhs is None:
        return lhs is None and rhs is None

    return all(abs(float(a) - float(b)) <= epsilon for a, b in zip(lhs, rhs))


def face_payloads_equal(lhs_faces, rhs_faces):
    if lhs_faces is rhs_faces:
        return True
    if lhs_faces is None or rhs_faces is None:
        return lhs_faces is None and rhs_faces is None
    if len(lhs_faces) != len(rhs_faces):
        return False

    for lhs_face, rhs_face in zip(lhs_faces, rhs_faces):
        if dict(lhs_face.get("blendshapes", {})) != dict(rhs_face.get("blendshapes", {})):
            return False
        if not quaternions_close(lhs_face.get("head_quaternion"), rhs_face.get("head_quaternion")):
            return False
    return True


def parse_packet_text(packet_text):
    try:
        packet = json.loads(packet_text)
    except json.JSONDecodeError:
        return None

    return sanitize_packet_payload(packet)


def parse_schema_message(raw_message):
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
        if isinstance(name, str):
            sanitized_names.append(name)

    return sanitized_names


def parse_binary_packet(packet_bytes, schema_names):
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
    faces_payload = []

    for _face_index in range(face_count):
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
            try:
                head_pose_values = struct.unpack_from(
                    "<" + ("f" * HEAD_POSE_FLOAT_COUNT),
                    packet_bytes,
                    offset,
                )
            except struct.error:
                return None
            head_quaternion = sanitize_head_quaternion(
                {
                    "w": head_pose_values[3],
                    "x": head_pose_values[4],
                    "y": head_pose_values[5],
                    "z": head_pose_values[6],
                }
            )
            offset += head_pose_bytes
        else:
            head_quaternion = None

        if flags & FACE_FLAG_TRANSFORMATION_MATRIX:
            matrix_bytes = TRANSFORMATION_MATRIX_FLOAT_COUNT * 4
            if len(packet_bytes) - offset < matrix_bytes:
                return None
            offset += matrix_bytes

        blendshape_bytes = blendshape_count * 4
        if len(packet_bytes) - offset < blendshape_bytes:
            return None

        face_blendshapes = {}
        for blendshape_index in range(blendshape_count):
            try:
                value = struct.unpack_from("<f", packet_bytes, offset)[0]
            except struct.error:
                return None
            offset += 4
            face_blendshapes[schema_names[blendshape_index]] = clamp01(value)

        faces_payload.append(
            {
                "blendshapes": face_blendshapes,
                "head_quaternion": head_quaternion,
            }
        )

    return {
        "faces": faces_payload,
        "face_count": max(0, face_count),
        "sent_at": str(frame_timestamp_ms),
    }

