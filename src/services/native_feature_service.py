from __future__ import annotations

import logging

from ..licensing.feature_access import get_feature_status
from ..licensing.registry import get_feature_spec
from ..native.licensed_wrapper import get_native_wrapper
from ._native_feature_support import (
    get_feature_lock_reason,
    native_reason_requires_redownload,
    sync_license_state_to_native,
)
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
        return (
            status.get("effective_state") in {"ready", "session_warning"}
            and bool(status.get("native_authorized", False))
        )

    def get_feature_status(self):
        status = get_feature_status(self.feature_id)
        native_status = self.get_native_authorization_status()
        status["native_authorized"] = bool(native_status.get("authorized", False))
        status["native_reason"] = str(native_status.get("reason", "") or "")
        status["native_expires_at"] = int(native_status.get("expires_at", 0) or 0)

        if status["effective_state"] in {"ready", "session_warning"} and not status["native_authorized"]:
            status["native_state"] = "validation_failed"
            native_reason = status["native_reason"]
            if native_reason_requires_redownload(native_reason):
                status["effective_state"] = "needs_redownload"
                status["message"] = native_reason or f"{self.spec.label} native validation failed."
                status["action"] = "download_binary"
                status["can_download"] = True
                status["can_retry"] = True
            else:
                status["effective_state"] = "session_warning"
                status["message"] = native_reason or f"{self.spec.label} native authorization is syncing."
                status["action"] = "open_preferences"
                status["can_download"] = False
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
            get_license_status=self.wrapper.get_license_status,
            apply_grant=self.wrapper.apply_native_grant,
            clear_license_state=self.wrapper.clear_license_state,
        )

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError(self.spec.label, self.get_lock_reason())
