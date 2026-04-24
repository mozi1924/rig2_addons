from .loader import load_native_extension_result

_LOAD_RESULT = load_native_extension_result("rig2_face_cap")
MODULE = _LOAD_RESULT.module
IS_NATIVE = bool(_LOAD_RESULT.is_available)
LOAD_ERROR = _LOAD_RESULT.error

def is_native_backend():
    return IS_NATIVE


def backend():
    return MODULE


def is_feature_unlocked():
    return IS_NATIVE


def get_lock_reason():
    return LOAD_ERROR


def backend_path():
    return _LOAD_RESULT.module_path
