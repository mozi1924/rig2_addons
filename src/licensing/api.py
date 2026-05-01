from .registry import FEATURE_FACE_CAP, FEATURE_MIFRAMES, FEATURE_R2BB, iter_public_api_feature_specs

_EMPTY_PROVIDER_STATUS = {
    "provider_available": False,
    "provider_ready": False,
    "activated": False,
    "product": "",
    "tier": "",
    "features": {},
    "warnings": [],
    "reason": "provider_missing",
}


def _copy_features(features):
    if not isinstance(features, dict):
        return {}
    return {
        str(name): bool(enabled)
        for name, enabled in features.items()
    }


def _copy_warnings(warnings):
    copied = []
    if not isinstance(warnings, list):
        return copied
    for item in warnings:
        if not isinstance(item, dict):
            continue
        copied.append({
            "level": str(item.get("level", "") or ""),
            "message": str(item.get("message", "") or ""),
            "action_required": bool(item.get("action_required", False)),
        })
    return copied


def _provider_status_with_reason(reason, *, provider_available, provider_ready):
    return {
        **_EMPTY_PROVIDER_STATUS,
        "provider_available": bool(provider_available),
        "provider_ready": bool(provider_ready),
        "reason": str(reason or "internal_error"),
    }


def _feature_message(reason, feature_name):
    if reason == "ok":
        return f"Rig2 feature '{feature_name}' is available."
    if reason == "provider_missing":
        return "Rig2 licensing provider is unavailable. Install the Rig2 addon first."
    if reason == "provider_not_ready":
        return "Rig2 is installed but not enabled. Enable the Rig2 addon before using this feature."
    if reason == "unactivated":
        return "Rig2 license is not activated. Activate it in Rig2 Addon Preferences."
    if reason == "unlicensed":
        return (
            f"Rig2 feature '{feature_name}' is not included in the current license tier. "
            "Check Rig2 Addon Preferences."
        )
    if reason == "session_error":
        return (
            "Rig2 license session needs attention. Re-activate or sync it in Rig2 Addon Preferences."
        )
    return "Rig2 licensing status could not be determined due to an internal error."


def get_provider_status():
    """Return a stable, primitives-only snapshot of Rig2 licensing availability."""
    try:
        from . import is_runtime_ready
    except (ImportError, ModuleNotFoundError):
        return dict(_EMPTY_PROVIDER_STATUS)
    except Exception:
        return _provider_status_with_reason(
            "internal_error",
            provider_available=False,
            provider_ready=False,
        )

    provider_ready = bool(is_runtime_ready())
    if not provider_ready:
        return _provider_status_with_reason(
            "provider_not_ready",
            provider_available=True,
            provider_ready=False,
        )

    try:
        from .manager import get_license_manager

        manager = get_license_manager()
        status = manager.get_status()
        session = getattr(getattr(manager, "_client", None), "session", None)
    except (ImportError, ModuleNotFoundError):
        return _provider_status_with_reason(
            "provider_missing",
            provider_available=False,
            provider_ready=False,
        )
    except Exception:
        return _provider_status_with_reason(
            "internal_error",
            provider_available=True,
            provider_ready=True,
        )

    activated = bool(status.get("activated"))
    if activated:
        reason = "ok"
    elif session is None:
        reason = "unactivated"
    else:
        reason = "session_error"

    return {
        "provider_available": True,
        "provider_ready": True,
        "activated": activated,
        "product": str(status.get("product", "") or ""),
        "tier": str(status.get("tier", "") or ""),
        "features": _copy_features(status.get("features", {}) if activated else {}),
        "warnings": _copy_warnings(status.get("warnings", [])),
        "reason": reason,
    }


def get_feature_access(feature_name):
    """Return feature-level access for sibling addons consuming Rig2 licensing."""
    feature_name = str(feature_name or "")
    provider_status = get_provider_status()
    reason = str(provider_status.get("reason", "internal_error") or "internal_error")
    activated = bool(provider_status.get("activated"))

    if reason != "ok":
        return {
            "feature": feature_name,
            "available": False,
            "activated": activated,
            "licensed": False,
            "reason": reason,
            "message": _feature_message(reason, feature_name),
        }

    supported_features = {spec.feature_id for spec in iter_public_api_feature_specs()}
    if feature_name not in supported_features:
        return {
            "feature": feature_name,
            "available": False,
            "activated": activated,
            "licensed": False,
            "reason": "internal_error",
            "message": "Unknown Rig2 feature constant. Use a documented FEATURE_* value.",
        }

    licensed = bool(provider_status.get("features", {}).get(feature_name, False))
    reason = "ok" if licensed else "unlicensed"
    return {
        "feature": feature_name,
        "available": licensed,
        "activated": activated,
        "licensed": licensed,
        "reason": reason,
        "message": _feature_message(reason, feature_name),
    }


def is_feature_licensed(feature_name):
    """Return True when a sibling addon may use the requested Rig2 feature."""
    return bool(get_feature_access(feature_name).get("licensed"))
