from .loader import load_native_extension_result

FACE_CAP_NATIVE_API_VERSION = 2

_REQUIRED_CALLABLES = (
    "backend_name",
    "clamp01",
    "discover_local_ipv4",
    "face_payloads_equal",
    "parse_binary_packet",
    "parse_packet_text",
    "parse_schema_message",
    "quaternions_close",
    "resolve_transport_encoding",
    "sanitize_head_quaternion",
    "sniff_packet_type",
    "load_offline_face_cap_payload",
    "start_receiver",
    "stop_receiver",
    "poll_latest_packet",
    "get_receiver_stats",
)

_REQUIRED_ATTRIBUTES = (
    "RIG2_FACE_CAP_API_VERSION",
    "BINARY_SUBPROTOCOL",
    "JSON_SUBPROTOCOL",
    "WEBSOCKET_MAGIC",
)

_LOAD_RESULT = load_native_extension_result(
    "rig2_face_cap",
    required_callables=_REQUIRED_CALLABLES,
    required_attributes=_REQUIRED_ATTRIBUTES,
    api_version_attr="RIG2_FACE_CAP_API_VERSION",
    expected_api_version=FACE_CAP_NATIVE_API_VERSION,
)
MODULE = _LOAD_RESULT.module
IS_NATIVE = bool(_LOAD_RESULT.is_available)
LOAD_ERROR = _LOAD_RESULT.error

def is_native_backend():
    return IS_NATIVE


def backend():
    return MODULE


def is_feature_unlocked():
    return IS_NATIVE


def get_lock_reason():
    return LOAD_ERROR


def backend_path():
    return _LOAD_RESULT.module_path
