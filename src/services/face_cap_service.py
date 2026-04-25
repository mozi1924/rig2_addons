from ..native.face_cap_wrapper import backend as face_cap_backend
from ..native.face_cap_wrapper import is_native_backend as face_cap_is_native_backend
from ..native.face_cap_wrapper import is_feature_unlocked as face_cap_is_feature_unlocked
from ..native.face_cap_wrapper import get_lock_reason as face_cap_get_lock_reason
from .errors import FeatureLockedError


class _LockedFaceCapBackend:
    """Safe backend shim used when Face Capture native binary is unavailable."""

    BINARY_SUBPROTOCOL = "r2fmc.bin.v1"
    JSON_SUBPROTOCOL = "r2fmc.json.v1"
    WEBSOCKET_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, lock_reason):
        self._lock_reason = str(lock_reason or "").strip()

    def backend_name(self):
        return "locked"

    def _raise_locked(self):
        raise FeatureLockedError("Face Capture", self._lock_reason)

    @staticmethod
    def clamp01(value):
        try:
            v = float(value)
        except Exception:
            v = 0.0
        return max(0.0, min(1.0, v))

    @staticmethod
    def discover_local_ipv4(_preferred_host=""):
        return ""

    @staticmethod
    def face_payloads_equal(left, right):
        return left == right

    @staticmethod
    def parse_binary_packet(_packet_bytes, _schema_names):
        return None

    @staticmethod
    def parse_packet_text(_raw_message):
        return None

    @staticmethod
    def parse_schema_message(_raw_message):
        return None

    @staticmethod
    def quaternions_close(left, right, tolerance=1e-4):
        if left is None or right is None:
            return False
        try:
            if len(left) != len(right):
                return False
            return all(abs(float(l) - float(r)) <= tolerance for l, r in zip(left, right))
        except Exception:
            return False

    @staticmethod
    def resolve_transport_encoding(protocol, _raw_message=None):
        if protocol == _LockedFaceCapBackend.BINARY_SUBPROTOCOL:
            return "binary"
        if protocol == _LockedFaceCapBackend.JSON_SUBPROTOCOL:
            return "json"
        return None

    @staticmethod
    def sanitize_head_quaternion(head_quaternion):
        if not head_quaternion:
            return (1.0, 0.0, 0.0, 0.0)
        return head_quaternion

    @staticmethod
    def sniff_packet_type(raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            return "binary"
        if isinstance(raw_message, str):
            return "blendshapes"
        return ""

    def load_offline_face_cap_payload(self, _filepath):
        self._raise_locked()

    def start_receiver(self, _host, _port, _options=None):
        self._raise_locked()

    @staticmethod
    def stop_receiver():
        return None

    @staticmethod
    def poll_latest_packet():
        return None

    @staticmethod
    def get_receiver_stats():
        return {
            "host": "",
            "port": 0,
            "is_listening": False,
            "bind_failed": False,
            "client_address": "",
            "packet_count": 0,
            "dropped_packet_count": 0,
            "last_packet_time": 0.0,
            "last_sent_at": "",
            "status_message": "Stopped",
            "last_error": "",
            "transport_mode": "websocket",
            "transport_encoding": None,
        }


class FaceCapBackendService:
    """
    Centralized backend access for FaceCap logic.

    This is the intended seam for future:
    - entitlement checks
    - binary availability checks
    - on-demand downloads
    - version compatibility checks
    """

    def __init__(self):
        self._backend = None

    def get_backend(self):
        if self._backend is None:
            if self.is_feature_unlocked():
                self._backend = face_cap_backend()
            else:
                self._backend = _LockedFaceCapBackend(self.get_lock_reason())
        return self._backend

    def is_native_backend(self):
        return face_cap_is_native_backend()

    def is_feature_unlocked(self):
        return face_cap_is_feature_unlocked()

    def get_lock_reason(self):
        reason = face_cap_get_lock_reason()
        return reason or "Face Capture native backend is not unlocked."

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError("Face Capture", self.get_lock_reason())

    def get_backend_name(self):
        backend = self.get_backend()
        backend_name = getattr(backend, "backend_name", None)
        if callable(backend_name):
            try:
                return str(backend_name())
            except Exception:
                pass
        return "native" if self.is_native_backend() else "locked"

    def get_runtime_bindings(self):
        backend = self.get_backend()
        return {
            "clamp01": backend.clamp01,
            "discover_local_ipv4": backend.discover_local_ipv4,
            "face_payloads_equal": backend.face_payloads_equal,
            "parse_binary_packet": backend.parse_binary_packet,
            "parse_packet_text": backend.parse_packet_text,
            "parse_schema_message": backend.parse_schema_message,
            "quaternions_close": backend.quaternions_close,
            "resolve_transport_encoding": backend.resolve_transport_encoding,
            "sanitize_head_quaternion": backend.sanitize_head_quaternion,
            "sniff_packet_type": backend.sniff_packet_type,
            "start_receiver": getattr(backend, "start_receiver", None),
            "stop_receiver": getattr(backend, "stop_receiver", None),
            "poll_latest_packet": getattr(backend, "poll_latest_packet", None),
            "get_receiver_stats": getattr(backend, "get_receiver_stats", None),
            "BINARY_SUBPROTOCOL": backend.BINARY_SUBPROTOCOL,
            "JSON_SUBPROTOCOL": backend.JSON_SUBPROTOCOL,
            "WEBSOCKET_MAGIC": backend.WEBSOCKET_MAGIC,
        }

    def load_offline_face_cap_payload(self, filepath):
        self.require_feature_unlocked()
        return self.get_backend().load_offline_face_cap_payload(filepath)


_face_cap_backend_service = FaceCapBackendService()


def get_face_cap_backend_service():
    return _face_cap_backend_service
