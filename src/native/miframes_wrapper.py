from ..licensing.registry import FEATURE_MIFRAMES
from .licensed_wrapper import get_native_wrapper


def _wrapper():
    return get_native_wrapper(FEATURE_MIFRAMES)


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


def set_license_state(device_id, expires_at, hmac_proof):
    _wrapper().set_license_state(device_id, expires_at, hmac_proof)


def verify_integrity(file_hashes):
    _wrapper().verify_integrity(file_hashes)


def get_license_status():
    return _wrapper().get_license_status()
