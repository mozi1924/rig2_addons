import logging

from ..licensing.registry import FEATURE_MIFRAMES
from .errors import FeatureLockedError
from .native_feature_service import NativeLicensedFeatureService

_log = logging.getLogger(__name__)


class _LockedMiframesBackend:
    def __init__(self, lock_reason):
        self._lock_reason = str(lock_reason or "").strip()

    def _raise_locked(self):
        raise FeatureLockedError("MIFrames", self._lock_reason)

    def get_models(self):
        return {}

    def get_model_config(self, _model_key=None):
        return None

    def plan_miframes_keyframe_ops(self, _data, _config, _start_frame, _fps_scale):
        self._raise_locked()


class MiframesBackendService(NativeLicensedFeatureService):
    def __init__(self):
        super().__init__(FEATURE_MIFRAMES, _log)

    def build_locked_backend(self, lock_reason):
        return _LockedMiframesBackend(lock_reason)

    def plan_miframes_keyframe_ops(self, data, config, start_frame, fps_scale):
        self.require_feature_unlocked()
        return self.get_backend().plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)

    def get_models(self):
        if not self.is_feature_unlocked():
            return {}
        getter = getattr(self.get_backend(), "get_models", None)
        if callable(getter):
            return getter()
        return {}

    def get_model_config(self, model_key):
        if not self.is_feature_unlocked():
            return None
        getter = getattr(self.get_backend(), "get_model_config", None)
        if callable(getter):
            return getter(model_key)
        return None


_miframes_backend_service = MiframesBackendService()


def get_miframes_backend_service():
    return _miframes_backend_service
