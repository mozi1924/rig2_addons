"""Python fallback entrypoints for face capture logic."""

from .offline_loader import (
    extract_faces,
    extract_frame_payloads,
    extract_frame_position,
    extract_schema_names,
    extract_video_fps,
    load_offline_face_cap_payload,
    normalize_face_payload,
    normalize_head_quaternion,
)
from .protocol import (
    BINARY_SUBPROTOCOL,
    JSON_SUBPROTOCOL,
    WEBSOCKET_MAGIC,
    clamp01,
    discover_local_ipv4,
    face_payloads_equal,
    parse_binary_packet,
    parse_packet_text,
    parse_schema_message,
    quaternions_close,
    resolve_transport_encoding,
    sanitize_head_quaternion,
    sanitize_packet_payload,
    sniff_packet_type,
)


def backend_name():
    return "python"
