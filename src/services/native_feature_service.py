from __future__ import annotations

import logging

from ..licensing.feature_access import get_feature_status
from ..licensing.registry import get_feature_spec
from ..native.licensed_wrapper import get_native_wrapper
from ._native_feature_support import (
    get_feature_lock_reason,
    native_reason_allows_grant_refresh,
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
        try:
            status = get_feature_status(self.feature_id, probe_native=True)
        except TypeError:
            # Backward-compatible for tests or older shims that only accept
            # positional feature_id.
            status = get_feature_status(self.feature_id)
        native_status = self.get_native_authorization_status()
        status["native_authorized"] = bool(native_status.get("authorized", False))
        status["native_reason"] = str(native_status.get("reason", "") or "")
        status["native_expires_at"] = int(native_status.get("expires_at", 0) or 0)

        if status["effective_state"] in {"ready", "session_warning"} and not status["native_authorized"]:
            native_reason = status["native_reason"]
            if bool(native_status.get("needs_redownload", False)):
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
                "needs_redownload": False,
            }
        try:
            raw = self.wrapper.get_license_status()
        except Exception as exc:
            return {"authorized": False, "reason": str(exc), "expires_at": 0, "needs_redownload": False}

        if not isinstance(raw, dict) or not raw:
            return {
                "authorized": False,
                "reason": "Native authorization state is unavailable. Re-download the binary.",
                "expires_at": 0,
                "needs_redownload": True,
            }
        authorized = bool(raw.get("authorized", False))
        reason = str(raw.get("reason", "") or "")
        needs_redownload = bool(raw.get("needs_redownload", False))
        if (not authorized) and (not needs_redownload) and native_reason_allows_grant_refresh(reason):
            # Integrity reasons (digest/size/manifest mismatch, etc.) should be
            # surfaced as a binary re-download action, not a generic re-sync hint.
            needs_redownload = True
        return {
            "authorized": authorized,
            "reason": reason,
            "expires_at": int(raw.get("expires_at", 0) or 0),
            "needs_redownload": needs_redownload,
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

    def sync_license_to_native(self, *, allow_network=True):
        sync_license_state_to_native(
            logger=self._log,
            feature_id=self.feature_id,
            get_license_status=self.wrapper.get_license_status,
            apply_grant=self.wrapper.apply_native_grant,
            clear_license_state=self.wrapper.clear_license_state,
            allow_network=allow_network,
        )

    def require_feature_unlocked(self):
        if self.is_feature_unlocked():
            return
        raise FeatureLockedError(self.spec.label, self.get_lock_reason())

    def call_unlocked_backend(self, method_name: str, /, *args, **kwargs):
        """Call a backend method after enforcing unlocked feature access."""
        self.require_feature_unlocked()
        method = getattr(self.get_backend(), method_name)
        return method(*args, **kwargs)

    def call_optional_backend(self, method_name: str, /, *args, default=None, **kwargs):
        """Call a backend method only when feature is unlocked and callable."""
        if not self.is_feature_unlocked():
            return default
        method = getattr(self.get_backend(), method_name, None)
        if not callable(method):
            return default
        return method(*args, **kwargs)
