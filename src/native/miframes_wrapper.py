from .loader import build_native_module_path, load_native_extension_result

MIFRAMES_NATIVE_API_VERSION = 2

_REQUIRED_CALLABLES = (
    "backend_name",
    "get_models",
    "get_model_config",
    "plan_miframes_keyframe_ops",
    "set_license_state",
    "verify_integrity",
)

_REQUIRED_ATTRIBUTES = (
    "RIG2_MIFRAMES_API_VERSION",
)

_LOAD_RESULT = None
MODULE = None
IS_NATIVE = False
LOAD_ERROR = ""


def refresh_native_backend():
    global _LOAD_RESULT, MODULE, IS_NATIVE, LOAD_ERROR
    _LOAD_RESULT = load_native_extension_result(
        "rig2_miframes",
        required_callables=_REQUIRED_CALLABLES,
        required_attributes=_REQUIRED_ATTRIBUTES,
        api_version_attr="RIG2_MIFRAMES_API_VERSION",
        expected_api_version=MIFRAMES_NATIVE_API_VERSION,
    )
    MODULE = _LOAD_RESULT.module
    IS_NATIVE = bool(_LOAD_RESULT.is_available)
    LOAD_ERROR = _LOAD_RESULT.error
    return _LOAD_RESULT


def get_load_state():
    if _LOAD_RESULT is None:
        refresh_native_backend()
    return {
        "module_name": "rig2_miframes",
        "module_path": _LOAD_RESULT.module_path if _LOAD_RESULT else "",
        "error": _LOAD_RESULT.error if _LOAD_RESULT else "",
        "is_available": bool(_LOAD_RESULT and _LOAD_RESULT.is_available),
        "candidate_paths": tuple(build_native_module_path("rig2_miframes")),
    }


refresh_native_backend()

def is_native_backend():
    if _LOAD_RESULT is None:
        refresh_native_backend()
    return IS_NATIVE


def backend():
    if _LOAD_RESULT is None:
        refresh_native_backend()
    return MODULE


def is_feature_unlocked():
    return IS_NATIVE


def get_lock_reason():
    if _LOAD_RESULT is None:
        refresh_native_backend()
    return LOAD_ERROR


def backend_path():
    if _LOAD_RESULT is None:
        refresh_native_backend()
    return _LOAD_RESULT.module_path


def set_license_state(device_id, expires_at, hmac_proof):
    """Propagate license state into the native module."""
    if MODULE is None:
        return
    setter = getattr(MODULE, "set_license_state", None)
    if callable(setter):
        setter(device_id, expires_at, hmac_proof)


def verify_integrity(file_hashes):
    """Verify Python source file integrity against native module expectations."""
    if MODULE is None:
        return
    verifier = getattr(MODULE, "verify_integrity", None)
    if callable(verifier):
        verifier(file_hashes)
