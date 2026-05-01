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
from ._native_feature_support import (
    get_feature_lock_reason,
    is_feature_licensed,
    sync_license_state_to_native,
)

_log = logging.getLogger(__name__)

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
        return is_feature_licensed(FEATURE_MIFRAMES)

    def get_lock_reason(self):
        return get_feature_lock_reason(
            feature_label="MIFrames",
            binary_available=_miframes_binary_available,
            binary_lock_reason=_miframes_binary_lock_reason,
            feature_name=FEATURE_MIFRAMES,
        )

    def sync_license_to_native(self):
        """Propagate the current license state to the C++ native module."""
        sync_license_state_to_native(
            logger=_log,
            backend_label="miframes",
            feature_unlocked=self.is_feature_unlocked,
            compute_proof=compute_miframes_proof,
            set_license_state=_miframes_set_license_state,
            verify_func=_miframes_verify_integrity,
        )

    @staticmethod
    def _verify_source_integrity():
        from ._native_feature_support import verify_source_integrity

        verify_source_integrity(_miframes_verify_integrity)

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
