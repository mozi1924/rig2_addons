from ..native.miframes_wrapper import backend as miframes_backend
from ..native.miframes_wrapper import is_native_backend as miframes_is_native_backend
from ..native.miframes_wrapper import is_feature_unlocked as miframes_is_feature_unlocked
from ..native.miframes_wrapper import get_lock_reason as miframes_get_lock_reason
from .errors import FeatureLockedError


class MiframesBackendService:
    """
    Centralized backend access for miframes planning logic.

    This service mirrors the face_cap service shape so we can move both
    features to native backends with minimal operator changes.
    """

    def __init__(self):
        self._backend = None

    def get_backend(self):
        if self._backend is None:
            self._backend = miframes_backend()
        return self._backend

    def is_native_backend(self):
        return miframes_is_native_backend()

    def is_feature_unlocked(self):
        return miframes_is_feature_unlocked()

    def get_lock_reason(self):
        reason = miframes_get_lock_reason()
        return reason or "MIFrames native backend is not unlocked."

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError("MIFrames", self.get_lock_reason())

    def get_backend_name(self):
        backend = self.get_backend()
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
        getter = getattr(backend, "get_models", None)
        if callable(getter):
            return getter()
        return {}

    def get_model_config(self, model_key):
        if not self.is_feature_unlocked():
            return None
        backend = self.get_backend()
        getter = getattr(backend, "get_model_config", None)
        if callable(getter):
            return getter(model_key)
        return None


_miframes_backend_service = MiframesBackendService()


def get_miframes_backend_service():
    return _miframes_backend_service
