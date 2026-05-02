from __future__ import annotations

from dataclasses import dataclass

from .loader import build_native_module_path, load_native_extension_result
from ..licensing.registry import get_feature_spec


@dataclass
class NativeFeatureWrapper:
    feature_id: str
    _load_result: object | None = None
    _module: object | None = None
    _is_native: bool = False
    _load_error: str = ""

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

    def apply_native_grant(self, grant_token, jwks_json, addon_root):
        module = self.backend()
        applier = getattr(module, "apply_native_grant", None) if module is not None else None
        if callable(applier):
            applier(grant_token, jwks_json, addon_root, self.backend_path())

    def clear_license_state(self):
        module = self.backend()
        clearer = getattr(module, "clear_license_state", None) if module is not None else None
        if callable(clearer):
            clearer()

    def get_license_status(self):
        module = self.backend()
        getter = getattr(module, "get_license_status", None) if module is not None else None
        if callable(getter):
            return getter() or {}
        return {}


_WRAPPERS: dict[str, NativeFeatureWrapper] = {}


def get_native_wrapper(feature_id: str) -> NativeFeatureWrapper:
    wrapper = _WRAPPERS.get(feature_id)
    if wrapper is None:
        wrapper = NativeFeatureWrapper(feature_id=feature_id)
        _WRAPPERS[feature_id] = wrapper
    return wrapper
