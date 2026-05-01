import logging

from ..native.face_cap_wrapper import backend as face_cap_backend
from ..native.face_cap_wrapper import is_native_backend as face_cap_is_native_backend
from ..native.face_cap_wrapper import is_feature_unlocked as _face_cap_binary_available
from ..native.face_cap_wrapper import get_lock_reason as _face_cap_binary_lock_reason
from ..native.face_cap_wrapper import set_license_state as _face_cap_set_license_state
from ..native.face_cap_wrapper import verify_integrity as _face_cap_verify_integrity
from ..licensing.config import FEATURE_FACE_CAP
from ..licensing._hmac_proof import compute_face_cap_proof
from .errors import FeatureLockedError

_log = logging.getLogger(__name__)


class _LockedFaceCapBackend:
    """Safe backend shim used when Face Capture native backend is unavailable."""

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


def _is_license_valid():
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_feature_licensed(FEATURE_FACE_CAP)
    except Exception:
        return False


def _is_license_activated():
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_activated()
    except Exception:
        return False


class FaceCapBackendService:
    """Centralized backend access for FaceCap logic.

    Combines native binary availability and Orbisauth license checks
    to gate the commercial Face Capture feature.
    """

    def get_backend(self):
        if self.is_feature_unlocked():
            return face_cap_backend()
        return _LockedFaceCapBackend(self.get_lock_reason())

    def is_native_backend(self):
        return face_cap_is_native_backend()

    def is_feature_unlocked(self):
        if not _face_cap_binary_available():
            return False
        return _is_license_valid()

    def get_lock_reason(self):
        if not _face_cap_binary_available():
            return (
                _face_cap_binary_lock_reason()
                or "Face Capture native backend is not installed."
            )
        if not _is_license_activated():
            return "License not activated. Activate your license in Addon Preferences."
        if not _is_license_valid():
            return "Face Capture is not included in your license tier."
        return "Face Capture is not unlocked."

    def sync_license_to_native(self):
        """Propagate the current license state to the C++ native module."""
        try:
            from ..licensing.manager import get_license_manager
            mgr = get_license_manager()
            device_id = mgr.get_device_id()

            # First, verify Python source integrity in the native module.
            self._verify_source_integrity()

            if self.is_feature_unlocked():
                expires_at, hmac_proof = compute_face_cap_proof(device_id)
                _face_cap_set_license_state(device_id, expires_at, hmac_proof)
            else:
                _face_cap_set_license_state(device_id, 0, "invalid")
        except Exception as exc:
            _log.debug("Failed to sync license to native face_cap: %s", exc)

    @staticmethod
    def _verify_source_integrity():
        """Compute SHA-256 hashes of critical Python files and verify in C++."""
        import hashlib
        import os

        base_dir = os.path.dirname(os.path.dirname(__file__))
        files = {
            "face_cap_service.py": os.path.join(base_dir, "services", "face_cap_service.py"),
            "miframes_service.py": os.path.join(base_dir, "services", "miframes_service.py"),
            "manager.py": os.path.join(base_dir, "licensing", "manager.py"),
        }

        hashes = {}
        for fname, fpath in files.items():
            try:
                with open(fpath, "rb") as fh:
                    hashes[fname] = hashlib.sha256(fh.read()).hexdigest()
            except Exception:
                hashes[fname] = ""

        try:
            _face_cap_verify_integrity(hashes)
        except Exception:
            pass

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
