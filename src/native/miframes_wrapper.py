from .loader import load_native_extension_result

MIFRAMES_NATIVE_API_VERSION = 1

_REQUIRED_CALLABLES = (
    "backend_name",
    "get_models",
    "get_model_config",
    "plan_miframes_keyframe_ops",
)

_REQUIRED_ATTRIBUTES = (
    "RIG2_MIFRAMES_API_VERSION",
)

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
