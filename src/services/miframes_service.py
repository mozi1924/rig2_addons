from ..native.miframes_wrapper import backend as miframes_backend
from ..native.miframes_wrapper import is_native_backend as miframes_is_native_backend
from ..native.miframes_wrapper import is_feature_unlocked as _miframes_binary_available
from ..native.miframes_wrapper import get_lock_reason as _miframes_binary_lock_reason
from ..licensing.config import FEATURE_MIFRAMES
from .errors import FeatureLockedError


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


class MiframesBackendService:
    """Centralized backend access for miframes planning logic.

    Combines native binary availability and Orbisauth license checks
    to gate the commercial MIFrames feature.
    """

    def get_backend(self):
        if self.is_feature_unlocked():
            return miframes_backend()
        # MIFrames has no locked-stub — return None.
        return None

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
