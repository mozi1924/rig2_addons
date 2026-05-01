import logging

from ..native.face_cap_wrapper import backend as face_cap_backend
from ..native.face_cap_wrapper import is_native_backend as face_cap_is_native_backend
from ..native.face_cap_wrapper import is_feature_unlocked as _face_cap_binary_available
from ..native.face_cap_wrapper import get_lock_reason as _face_cap_binary_lock_reason
from ..native.face_cap_wrapper import get_license_status as _face_cap_native_license_status
from ..native.face_cap_wrapper import set_license_state as _face_cap_set_license_state
from ..native.face_cap_wrapper import verify_integrity as _face_cap_verify_integrity
from ..licensing.config import FEATURE_FACE_CAP
from ..licensing._hmac_proof import compute_face_cap_proof
from ..licensing.feature_access import get_feature_status
from .errors import FeatureLockedError
from ._native_feature_support import (
    get_feature_lock_reason,
    sync_license_state_to_native,
)

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
        status = self.get_feature_status()
        return status.get("effective_state") in {"ready", "session_warning"}

    @staticmethod
    def _is_license_session_ready_for_native():
        status = get_feature_status(FEATURE_FACE_CAP)
        return status.get("effective_state") in {"ready", "session_warning"}

    def get_feature_status(self):
        status = get_feature_status(FEATURE_FACE_CAP)
        native_status = self.get_native_authorization_status()
        status["native_authorized"] = bool(native_status.get("authorized", False))
        status["native_reason"] = str(native_status.get("reason", "") or "")
        status["native_expires_at"] = int(native_status.get("expires_at", 0) or 0)

        if status["effective_state"] in {"ready", "session_warning"} and not status["native_authorized"]:
            status["effective_state"] = "needs_redownload"
            status["native_state"] = "validation_failed"
            status["message"] = (
                status["native_reason"] or "Face Capture native validation failed."
            )
            status["action"] = "download_binary"
            status["can_download"] = True
            status["can_retry"] = True

        return status

    def get_native_authorization_status(self):
        if not self.is_native_backend():
            return {
                "authorized": False,
                "reason": _face_cap_binary_lock_reason(),
                "expires_at": 0,
            }

        try:
            raw = _face_cap_native_license_status()
        except Exception as exc:
            return {
                "authorized": False,
                "reason": str(exc),
                "expires_at": 0,
            }

        if not isinstance(raw, dict) or not raw:
            return {
                "authorized": True,
                "reason": "",
                "expires_at": 0,
            }

        return {
            "authorized": bool(raw.get("authorized", False)),
            "reason": str(raw.get("reason", "") or ""),
            "expires_at": int(raw.get("expires_at", 0) or 0),
        }

    def get_lock_reason(self):
        status = self.get_feature_status()
        return (
            status.get("native_reason")
            or status.get("message")
            or get_feature_lock_reason(
                feature_label="Face Capture",
                binary_available=_face_cap_binary_available,
                binary_lock_reason=_face_cap_binary_lock_reason,
                feature_name=FEATURE_FACE_CAP,
            )
        )

    def sync_license_to_native(self):
        """Propagate the current license state to the C++ native module."""
        sync_license_state_to_native(
            logger=_log,
            backend_label="face_cap",
            feature_unlocked=self._is_license_session_ready_for_native,
            compute_proof=compute_face_cap_proof,
            set_license_state=_face_cap_set_license_state,
            verify_func=_face_cap_verify_integrity,
        )

    @staticmethod
    def _verify_source_integrity():
        from ._native_feature_support import verify_source_integrity

        verify_source_integrity(_face_cap_verify_integrity)

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
