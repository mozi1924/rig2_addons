from __future__ import annotations

import logging

from ..licensing.registry import get_feature_spec
from ..native.licensed_wrapper import get_native_wrapper


class NativeLicensedFeatureService:
    def __init__(self, feature_id: str, logger: logging.Logger):
        self.feature_id = feature_id
        self._log = logger

    @property
    def spec(self):
        return get_feature_spec(self.feature_id)

    @property
    def wrapper(self):
        return get_native_wrapper(self.feature_id)

    def get_backend(self):
        backend = self.wrapper.backend()
        if backend is not None:
            return backend
        return self.build_locked_backend(self.get_lock_reason())

    def build_locked_backend(self, lock_reason):
        raise NotImplementedError

    def is_native_backend(self):
        return self.wrapper.is_native_backend()

    def is_feature_unlocked(self):
        return True

    def get_feature_status(self):
        return {
            "effective_state": "ready",
            "message": f"{self.spec.label} is ready.",
            "label": self.spec.label,
        }

    def get_native_authorization_status(self):
        return {
            "authorized": True,
            "reason": "",
            "expires_at": 0,
            "needs_redownload": False,
        }

    def get_lock_reason(self):
        return ""

    def sync_license_to_native(self, *, allow_network=True):
        pass

    def require_feature_unlocked(self):
        return

    def call_unlocked_backend(self, method_name: str, /, *args, **kwargs):
        method = getattr(self.get_backend(), method_name)
        return method(*args, **kwargs)

    def call_optional_backend(self, method_name: str, /, *args, default=None, **kwargs):
        method = getattr(self.get_backend(), method_name, None)
        if not callable(method):
            return default
        return method(*args, **kwargs)
