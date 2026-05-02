from ..licensing.registry import FEATURE_R2BB
from .licensed_wrapper import get_native_wrapper


def _wrapper():
    return get_native_wrapper(FEATURE_R2BB)


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


def apply_native_grant(grant_token, jwks_json, addon_root):
    _wrapper().apply_native_grant(grant_token, jwks_json, addon_root)


def clear_license_state():
    _wrapper().clear_license_state()


def get_license_status():
    return _wrapper().get_license_status()
