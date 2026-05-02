from __future__ import annotations

from dataclasses import dataclass
import threading

from .loader import build_native_module_path, load_native_extension_result
from ..licensing.registry import get_feature_spec


@dataclass
class NativeFeatureWrapper:
    feature_id: str
    _load_result: object | None = None
    _module: object | None = None
    _is_native: bool = False
    _load_error: str = ""
    _license_status_cache: dict | None = None

    @property
    def spec(self):
        return get_feature_spec(self.feature_id)

    def refresh_native_backend(self):
        spec = self.spec
        self._load_result = load_native_extension_result(
            spec.native_module_name,
            required_callables=spec.required_callables,
            required_attributes=spec.required_attributes,
            api_version_attr=spec.native_api_version_attr,
            expected_api_version=spec.expected_native_api_version,
        )
        self._module = self._load_result.module
        self._is_native = bool(self._load_result.is_available)
        self._load_error = self._load_result.error
        if self._license_status_cache is None:
            self._license_status_cache = {
                "authorized": False,
                "reason": "",
                "expires_at": 0,
                "needs_redownload": False,
            }
        if not self._is_native and self._load_error:
            self._license_status_cache.update(
                {
                    "authorized": False,
                    "reason": str(self._load_error),
                    "expires_at": 0,
                    "needs_redownload": False,
                }
            )
        return self._load_result

    def _ensure_loaded(self):
        if self._load_result is None:
            self.refresh_native_backend()

    def get_load_state(self):
        self._ensure_loaded()
        return {
            "module_name": self.spec.native_module_name,
            "module_path": self._load_result.module_path if self._load_result else "",
            "error": self._load_result.error if self._load_result else "",
            "is_available": bool(self._load_result and self._load_result.is_available),
            "candidate_paths": tuple(build_native_module_path(self.spec.native_module_name)),
        }

    def is_native_backend(self):
        self._ensure_loaded()
        return self._is_native

    def backend(self):
        self._ensure_loaded()
        return self._module

    def is_feature_unlocked(self):
        return self.is_native_backend()

    def get_lock_reason(self):
        self._ensure_loaded()
        return self._load_error

    def backend_path(self):
        self._ensure_loaded()
        return self._load_result.module_path if self._load_result else ""

    @staticmethod
    def _allow_native_calls_in_current_thread():
        # Keep native authorization/status calls on Blender's main thread on
        # all platforms for deterministic behavior.
        return threading.current_thread() is threading.main_thread()

    def apply_native_grant(self, grant_token, trust_bundle_token, addon_root):
        if not self._allow_native_calls_in_current_thread():
            return
        module = self.backend()
        applier = getattr(module, "apply_native_grant", None) if module is not None else None
        if callable(applier):
            try:
                applier(grant_token, trust_bundle_token, addon_root, self.backend_path())
                if self._license_status_cache is None:
                    self._license_status_cache = {}
                # Native apply currently returns no success flag. We mark this as
                # optimistic and let protected native entrypoints enforce final auth.
                self._license_status_cache.update(
                    {
                        "authorized": True,
                        "reason": "",
                        "expires_at": 0,
                        "needs_redownload": False,
                    }
                )
            except Exception as exc:
                if self._license_status_cache is None:
                    self._license_status_cache = {}
                self._license_status_cache.update(
                    {
                        "authorized": False,
                        "reason": str(exc),
                        "expires_at": 0,
                        "needs_redownload": False,
                    }
                )
                raise
        else:
            if self._license_status_cache is None:
                self._license_status_cache = {}
            self._license_status_cache.update(
                {
                    "authorized": False,
                    "reason": "Native backend is unavailable or missing apply_native_grant.",
                    "expires_at": 0,
                    "needs_redownload": True,
                }
            )

    def clear_license_state(self, reason=""):
        if not self._allow_native_calls_in_current_thread():
            return
        module = self.backend()
        clearer = getattr(module, "clear_license_state", None) if module is not None else None
        if callable(clearer):
            clearer(reason)
        if self._license_status_cache is None:
            self._license_status_cache = {}
        self._license_status_cache.update(
            {
                "authorized": False,
                "reason": str(reason or ""),
                "expires_at": 0,
                "needs_redownload": False,
            }
        )

    def get_license_status(self):
        if self._license_status_cache is None:
            self._license_status_cache = {
                "authorized": False,
                "reason": "",
                "expires_at": 0,
                "needs_redownload": False,
            }
        if not self._allow_native_calls_in_current_thread():
            return dict(self._license_status_cache)
        module = self.backend()
        getter = getattr(module, "get_license_status", None) if module is not None else None
        if callable(getter):
            status = getter() or {}
            if isinstance(status, dict):
                self._license_status_cache.update(status)
                return dict(self._license_status_cache)
        return dict(self._license_status_cache)


_WRAPPERS: dict[str, NativeFeatureWrapper] = {}


def get_native_wrapper(feature_id: str) -> NativeFeatureWrapper:
    wrapper = _WRAPPERS.get(feature_id)
    if wrapper is None:
        wrapper = NativeFeatureWrapper(feature_id=feature_id)
        _WRAPPERS[feature_id] = wrapper
    return wrapper
