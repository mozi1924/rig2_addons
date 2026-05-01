import json
import logging
import os
import time
from typing import Any

from .config import FEATURE_FACE_CAP, FEATURE_MIFRAMES
from .paths import get_feature_status_path

_log = logging.getLogger(__name__)

FEATURE_DEFS = {
    FEATURE_FACE_CAP: {
        "label": "Face Capture",
        "module_name": "rig2_face_cap",
    },
    FEATURE_MIFRAMES: {
        "label": "MIFrames",
        "module_name": "rig2_miframes",
    },
}


def _empty_state():
    return {
        "features": {
            feature_name: {
                "last_download_failed": False,
                "last_download_error": "",
                "last_download_at": 0.0,
                "last_download_succeeded_at": 0.0,
            }
            for feature_name in FEATURE_DEFS
        }
    }


def _load_persisted_state():
    path = get_feature_status_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            merged = _empty_state()
            merged.update(data)
            feature_data = merged.get("features", {})
            merged["features"] = {
                feature_name: {
                    **_empty_state()["features"][feature_name],
                    **(feature_data.get(feature_name, {}) if isinstance(feature_data, dict) else {}),
                }
                for feature_name in FEATURE_DEFS
            }
            return merged
    except FileNotFoundError:
        pass
    except Exception as exc:
        _log.debug("Failed to load feature status state: %s", exc)
    return _empty_state()


def _save_persisted_state(state):
    path = get_feature_status_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temp_path = path + ".part"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    os.replace(temp_path, path)


def _update_feature_state(feature_name, **updates):
    state = _load_persisted_state()
    feature_state = dict(state["features"].get(feature_name, {}))
    feature_state.update(updates)
    state["features"][feature_name] = feature_state
    _save_persisted_state(state)
    return feature_state


def clear_feature_state():
    """Reset all persisted feature download state."""
    _save_persisted_state(_empty_state())


def _mark_download_success(feature_name):
    now = time.time()
    return _update_feature_state(
        feature_name,
        last_download_failed=False,
        last_download_error="",
        last_download_at=now,
        last_download_succeeded_at=now,
    )


def _mark_download_failure(feature_name, error):
    return _update_feature_state(
        feature_name,
        last_download_failed=True,
        last_download_error=str(error or "").strip(),
        last_download_at=time.time(),
    )


def get_feature_definition(feature_name):
    return FEATURE_DEFS[feature_name]


def _get_wrapper_module(feature_name):
    if feature_name == FEATURE_FACE_CAP:
        from ..native import face_cap_wrapper as wrapper

        return wrapper
    if feature_name == FEATURE_MIFRAMES:
        from ..native import miframes_wrapper as wrapper

        return wrapper
    raise KeyError(f"Unknown feature: {feature_name}")


def _get_license_manager():
    from .manager import get_license_manager

    return get_license_manager()


def _get_license_snapshot():
    manager = _get_license_manager()
    status = manager.get_status()
    session = getattr(getattr(manager, "_client", None), "session", None)
    features = {}
    if session is not None:
        features = dict(getattr(session, "features", {}) or {})
    warning_levels = [str(item.get("level", "")) for item in status.get("warnings", [])]
    return {
        "status": status,
        "session": session,
        "features": features,
        "has_session": session is not None,
        "refresh_expired": bool(status.get("is_refresh_expired")),
        "warning_levels": warning_levels,
    }


def _get_binary_snapshot(feature_name):
    wrapper = _get_wrapper_module(feature_name)
    wrapper.refresh_native_backend()
    load_state = wrapper.get_load_state()
    from ..native.loader import (
        get_primary_native_module_path,
        get_residual_native_module_paths,
        list_existing_native_module_paths,
    )

    module_name = get_feature_definition(feature_name)["module_name"]
    primary_path = get_primary_native_module_path(module_name)
    existing_paths = list_existing_native_module_paths(module_name)
    residual_paths = get_residual_native_module_paths(module_name)
    binary_present = bool(existing_paths)
    return {
        "wrapper": wrapper,
        "load_state": load_state,
        "binary_present": binary_present,
        "primary_path": primary_path,
        "existing_paths": existing_paths,
        "residual_paths": residual_paths,
    }


def _build_message(*, label, effective_state, download_error=""):
    if effective_state == "unactivated":
        return f"{label} is locked. Activate your license in Addon Preferences."
    if effective_state == "unlicensed":
        return f"{label} is not included in your current license tier. Check Addon Preferences."
    if effective_state == "binary_missing":
        return f"{label} binary is missing. Download it in Addon Preferences."
    if effective_state == "needs_redownload":
        return (
            f"{label} binary is outdated or incompatible with this addon version. "
            "Update the binary in Addon Preferences."
        )
    if effective_state == "download_failed":
        if download_error:
            return (
                f"{label} download failed: {download_error}. "
                "Retry from Addon Preferences."
            )
        return f"{label} download failed. Retry from Addon Preferences."
    if effective_state == "session_error":
        return f"{label} is locked because the license session expired. Re-activate it in Addon Preferences."
    if effective_state == "session_warning":
        return f"{label} is available, but your license needs attention in Addon Preferences."
    return f"{label} is ready."


def _build_action(effective_state):
    if effective_state == "unactivated":
        return "activate_license"
    if effective_state in {"binary_missing", "needs_redownload"}:
        return "download_binary"
    if effective_state == "download_failed":
        return "retry_download"
    if effective_state in {"unlicensed", "session_error", "session_warning"}:
        return "open_preferences"
    return "none"


def get_feature_status(feature_name):
    feature_def = get_feature_definition(feature_name)
    persisted_state = _load_persisted_state()["features"].get(feature_name, {})
    license_snapshot = _get_license_snapshot()
    binary_snapshot = _get_binary_snapshot(feature_name)
    wrapper = binary_snapshot["wrapper"]
    status = license_snapshot["status"]
    entitled = bool(license_snapshot["features"].get(feature_name, False))
    warning_levels = set(license_snapshot["warning_levels"])

    if not license_snapshot["has_session"]:
        effective_state = "unactivated"
        license_state = "missing"
    elif license_snapshot["refresh_expired"] or "ERROR" in warning_levels:
        effective_state = "session_error"
        license_state = "expired"
    elif not entitled:
        effective_state = "unlicensed"
        license_state = "licensed"
    elif not binary_snapshot["binary_present"]:
        effective_state = (
            "download_failed"
            if persisted_state.get("last_download_failed")
            else "binary_missing"
        )
        license_state = "licensed"
    elif binary_snapshot["residual_paths"]:
        effective_state = "needs_redownload"
        license_state = "licensed"
    elif not wrapper.is_native_backend():
        effective_state = "needs_redownload"
        license_state = "licensed"
    elif status.get("warnings"):
        effective_state = "session_warning"
        license_state = "warning"
    else:
        effective_state = "ready"
        license_state = "licensed"

    binary_state = "installed" if binary_snapshot["binary_present"] else "missing"
    if effective_state == "download_failed":
        binary_state = "download_failed"
    elif effective_state == "needs_redownload":
        binary_state = "invalid"

    native_state = "loaded" if wrapper.is_native_backend() else "unavailable"
    if effective_state == "ready":
        native_state = "authorized"
    elif effective_state == "session_warning":
        native_state = "authorized_warning"

    message = _build_message(
        label=feature_def["label"],
        effective_state=effective_state,
        download_error=persisted_state.get("last_download_error", ""),
    )
    if effective_state == "needs_redownload" and binary_snapshot["residual_paths"]:
        message = (
            f"{feature_def['label']} has leftover or duplicate native binaries. "
            "Update the binary in Addon Preferences."
        )
    action = _build_action(effective_state)
    return {
        "feature_name": feature_name,
        "label": feature_def["label"],
        "module_name": feature_def["module_name"],
        "license_state": license_state,
        "binary_state": binary_state,
        "native_state": native_state,
        "effective_state": effective_state,
        "message": message,
        "action": action,
        "can_download": effective_state in {"binary_missing", "needs_redownload", "download_failed"},
        "can_retry": effective_state in {"needs_redownload", "download_failed"},
        "download_error": persisted_state.get("last_download_error", ""),
        "warnings": list(status.get("warnings", [])),
        "module_path": binary_snapshot["load_state"].get("module_path", ""),
        "load_error": binary_snapshot["load_state"].get("error", ""),
        "primary_module_path": binary_snapshot["primary_path"],
        "existing_module_paths": binary_snapshot["existing_paths"],
        "residual_module_paths": binary_snapshot["residual_paths"],
    }


def get_all_feature_statuses():
    return {
        feature_name: get_feature_status(feature_name)
        for feature_name in FEATURE_DEFS
    }


def is_feature_ready(feature_name):
    return get_feature_status(feature_name)["effective_state"] in {"ready", "session_warning"}


def get_feature_action_hint(feature_name):
    return get_feature_status(feature_name)["message"]


def refresh_feature_runtime(feature_name=None):
    feature_names = [feature_name] if feature_name else list(FEATURE_DEFS)
    refreshed = {}
    for current_feature in feature_names:
        wrapper = _get_wrapper_module(current_feature)
        wrapper.refresh_native_backend()
        refreshed[current_feature] = wrapper.get_load_state()

    try:
        from . import sync_license_to_native_modules

        sync_license_to_native_modules()
    except Exception as exc:
        _log.debug("Failed to sync license to native modules after refresh: %s", exc)

    try:
        from ..modules.face_cap.runtime import get_runtime_service

        get_runtime_service().refresh_backend()
    except Exception as exc:
        _log.debug("Failed to refresh face_cap runtime: %s", exc)

    return refreshed


def download_feature_binary(feature_name, force=False):
    from ..native.downloader import ensure_native_binary

    feature_def = get_feature_definition(feature_name)
    try:
        ok = ensure_native_binary(feature_def["module_name"], force=force)
        if not ok:
            _mark_download_failure(feature_name, "Download not available for this feature.")
            return {
                "ok": False,
                "feature_name": feature_name,
                "error": "Download not available for this feature.",
            }
        _mark_download_success(feature_name)
        refresh_feature_runtime(feature_name)
        return {
            "ok": True,
            "feature_name": feature_name,
            "error": "",
        }
    except Exception as exc:
        _mark_download_failure(feature_name, exc)
        refresh_feature_runtime(feature_name)
        return {
            "ok": False,
            "feature_name": feature_name,
            "error": str(exc),
        }


def activate_and_prepare_features(license_key):
    manager = _get_license_manager()
    session = manager.activate(license_key)
    clear_feature_state()
    download_results = {}
    licensed_features = [
        feature_name
        for feature_name in FEATURE_DEFS
        if bool(getattr(session, "features", {}).get(feature_name, False))
    ]
    for feature_name in licensed_features:
        download_results[feature_name] = download_feature_binary(feature_name)
    refresh_feature_runtime()
    return {
        "session": session,
        "licensed_features": licensed_features,
        "download_results": download_results,
        "download_labels": {
            feature_name: FEATURE_DEFS[feature_name]["label"]
            for feature_name in licensed_features
        },
    }
