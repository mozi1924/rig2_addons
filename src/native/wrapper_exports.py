from __future__ import annotations

from .licensed_wrapper import get_native_wrapper


def install_feature_wrapper_exports(namespace, feature_id: str):
    """Install compatibility exports for feature wrapper modules."""

    def _wrapper():
        return get_native_wrapper(feature_id)

    def refresh_native_backend():
        return _wrapper().refresh_native_backend()

    def get_load_state():
        return _wrapper().get_load_state()

    def is_native_backend():
        return _wrapper().is_native_backend()

    def backend():
        return _wrapper().backend()

    def is_feature_unlocked():
        return _wrapper().is_feature_unlocked()

    def get_lock_reason():
        return _wrapper().get_lock_reason()

    def backend_path():
        return _wrapper().backend_path()

    def apply_native_grant(grant_token, trust_bundle_token, addon_root):
        _wrapper().apply_native_grant(grant_token, trust_bundle_token, addon_root)

    def clear_license_state():
        _wrapper().clear_license_state()

    def get_license_status():
        return _wrapper().get_license_status()

    namespace.update(
        {
            "_wrapper": _wrapper,
            "refresh_native_backend": refresh_native_backend,
            "get_load_state": get_load_state,
            "is_native_backend": is_native_backend,
            "backend": backend,
            "is_feature_unlocked": is_feature_unlocked,
            "get_lock_reason": get_lock_reason,
            "backend_path": backend_path,
            "apply_native_grant": apply_native_grant,
            "clear_license_state": clear_license_state,
            "get_license_status": get_license_status,
        }
    )
