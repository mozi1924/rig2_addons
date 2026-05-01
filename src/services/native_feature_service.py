from __future__ import annotations

import logging

from ..licensing.feature_access import get_feature_status
from ..licensing.registry import get_feature_spec
from ..native.licensed_wrapper import get_native_wrapper
from ._native_feature_support import get_feature_lock_reason, sync_license_state_to_native
from .errors import FeatureLockedError


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
        if self.is_feature_unlocked():
            return self.wrapper.backend()
        return self.build_locked_backend(self.get_lock_reason())

    def build_locked_backend(self, lock_reason):
        raise NotImplementedError

    def is_native_backend(self):
        return self.wrapper.is_native_backend()

    def is_feature_unlocked(self):
        status = self.get_feature_status()
        return status.get("effective_state") in {"ready", "session_warning"}

    def _is_license_session_ready_for_native(self):
        status = get_feature_status(self.feature_id)
        return status.get("effective_state") in {"ready", "session_warning"}

    def get_feature_status(self):
        status = get_feature_status(self.feature_id)
        native_status = self.get_native_authorization_status()
        status["native_authorized"] = bool(native_status.get("authorized", False))
        status["native_reason"] = str(native_status.get("reason", "") or "")
        status["native_expires_at"] = int(native_status.get("expires_at", 0) or 0)

        if status["effective_state"] in {"ready", "session_warning"} and not status["native_authorized"]:
            status["effective_state"] = "needs_redownload"
            status["native_state"] = "validation_failed"
            status["message"] = status["native_reason"] or f"{self.spec.label} native validation failed."
            status["action"] = "download_binary"
            status["can_download"] = True
            status["can_retry"] = True
        return status

    def get_native_authorization_status(self):
        if not self.is_native_backend():
            return {
                "authorized": False,
                "reason": self.wrapper.get_lock_reason(),
                "expires_at": 0,
            }
        try:
            raw = self.wrapper.get_license_status()
        except Exception as exc:
            return {"authorized": False, "reason": str(exc), "expires_at": 0}

        if not isinstance(raw, dict) or not raw:
            return {"authorized": True, "reason": "", "expires_at": 0}
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
                feature_label=self.spec.label,
                binary_available=self.wrapper.is_feature_unlocked,
                binary_lock_reason=self.wrapper.get_lock_reason,
                feature_name=self.feature_id,
            )
        )

    def sync_license_to_native(self):
        sync_license_state_to_native(
            logger=self._log,
            feature_id=self.feature_id,
            verify_func=self.wrapper.verify_integrity,
            set_license_state=self.wrapper.set_license_state,
        )

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError(self.spec.label, self.get_lock_reason())

    def get_backend_name(self):
        backend = self.get_backend()
        backend_name = getattr(backend, "backend_name", None)
        if callable(backend_name):
            try:
                return str(backend_name())
            except Exception:
                pass
        return "native" if self.is_native_backend() else "locked"
