from .loader import load_native_or_fallback


def _import_fallback():
    from ..logic.miframes import fallback as fallback_module

    return fallback_module


MODULE, IS_NATIVE = load_native_or_fallback("rig2_miframes", _import_fallback)


def is_native_backend():
    return IS_NATIVE


def backend():
    return MODULE

