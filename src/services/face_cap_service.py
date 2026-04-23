from ..native.face_cap_wrapper import backend as face_cap_backend
from ..native.face_cap_wrapper import is_native_backend as face_cap_is_native_backend


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
            self._backend = face_cap_backend()
        return self._backend

    def is_native_backend(self):
        return face_cap_is_native_backend()

    def get_backend_name(self):
        backend = self.get_backend()
        backend_name = getattr(backend, "backend_name", None)
        if callable(backend_name):
            try:
                return str(backend_name())
            except Exception:
                pass
        return "native" if self.is_native_backend() else "python"

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
            "BINARY_SUBPROTOCOL": backend.BINARY_SUBPROTOCOL,
            "JSON_SUBPROTOCOL": backend.JSON_SUBPROTOCOL,
            "WEBSOCKET_MAGIC": backend.WEBSOCKET_MAGIC,
        }

    def load_offline_face_cap_payload(self, filepath):
        return self.get_backend().load_offline_face_cap_payload(filepath)


_face_cap_backend_service = FaceCapBackendService()


def get_face_cap_backend_service():
    return _face_cap_backend_service

