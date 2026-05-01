import logging

from ..native.miframes_wrapper import backend as miframes_backend
from ..native.miframes_wrapper import is_native_backend as miframes_is_native_backend
from ..native.miframes_wrapper import is_feature_unlocked as _miframes_binary_available
from ..native.miframes_wrapper import get_lock_reason as _miframes_binary_lock_reason
from ..native.miframes_wrapper import set_license_state as _miframes_set_license_state
from ..native.miframes_wrapper import verify_integrity as _miframes_verify_integrity
from ..licensing.config import FEATURE_MIFRAMES
from ..licensing._hmac_proof import compute_miframes_proof
from .errors import FeatureLockedError

_log = logging.getLogger(__name__)


def _is_license_valid():
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_feature_licensed(FEATURE_MIFRAMES)
    except Exception:
        return False


def _is_license_activated():
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_activated()
    except Exception:
        return False


class _LockedMiframesBackend:
    """Safe backend shim used when MIFrames native backend is unavailable."""

    def __init__(self, lock_reason):
        self._lock_reason = str(lock_reason or "").strip()

    def backend_name(self):
        return "locked"

    def _raise_locked(self):
        raise FeatureLockedError("MIFrames", self._lock_reason)

    def get_models(self):
        return {}

    def get_model_config(self, _model_key=None):
        return None

    def plan_miframes_keyframe_ops(self, _data, _config, _start_frame, _fps_scale):
        self._raise_locked()


class MiframesBackendService:
    """Centralized backend access for miframes planning logic.

    Combines native binary availability and Orbisauth license checks
    to gate the commercial MIFrames feature.
    """

    def get_backend(self):
        if self.is_feature_unlocked():
            return miframes_backend()
        return _LockedMiframesBackend(self.get_lock_reason())

    def is_native_backend(self):
        return miframes_is_native_backend()

    def is_feature_unlocked(self):
        if not _miframes_binary_available():
            return False
        return _is_license_valid()

    def get_lock_reason(self):
        if not _miframes_binary_available():
            return (
                _miframes_binary_lock_reason()
                or "MIFrames native backend is not installed."
            )
        if not _is_license_activated():
            return "License not activated. Activate your license in Addon Preferences."
        if not _is_license_valid():
            return "MIFrames is not included in your license tier."
        return "MIFrames is not unlocked."

    def sync_license_to_native(self):
        """Propagate the current license state to the C++ native module."""
        try:
            from ..licensing.manager import get_license_manager
            mgr = get_license_manager()
            device_id = mgr.get_device_id()

            self._verify_source_integrity()

            if self.is_feature_unlocked():
                expires_at, hmac_proof = compute_miframes_proof(device_id)
                _miframes_set_license_state(device_id, expires_at, hmac_proof)
            else:
                _miframes_set_license_state(device_id, 0, "invalid")
        except Exception as exc:
            _log.debug("Failed to sync license to native miframes: %s", exc)

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
            _miframes_verify_integrity(hashes)
        except Exception:
            pass

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError("MIFrames", self.get_lock_reason())

    def get_backend_name(self):
        backend = self.get_backend()
        if backend is None:
            return "locked"
        backend_name = getattr(backend, "backend_name", None)
        if callable(backend_name):
            try:
                return str(backend_name())
            except Exception:
                pass
        return "native" if self.is_native_backend() else "locked"

    def plan_miframes_keyframe_ops(self, data, config, start_frame, fps_scale):
        self.require_feature_unlocked()
        backend = self.get_backend()
        return backend.plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)

    def get_models(self):
        if not self.is_feature_unlocked():
            return {}
        backend = self.get_backend()
        if backend is None:
            return {}
        getter = getattr(backend, "get_models", None)
        if callable(getter):
            return getter()
        return {}

    def get_model_config(self, model_key):
        if not self.is_feature_unlocked():
            return None
        backend = self.get_backend()
        if backend is None:
            return None
        getter = getattr(backend, "get_model_config", None)
        if callable(getter):
            return getter(model_key)
        return None


_miframes_backend_service = MiframesBackendService()


def get_miframes_backend_service():
    return _miframes_backend_service
