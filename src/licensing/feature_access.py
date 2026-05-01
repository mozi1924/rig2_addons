from __future__ import annotations

import json
import logging
import os
import threading
import time
from enum import Enum

from .paths import get_feature_status_path
from .registry import get_feature_spec, iter_feature_specs
from ..native.licensed_wrapper import get_native_wrapper

_log = logging.getLogger(__name__)


class FeatureVisibility(Enum):
    """Single source of truth for feature panel/module visibility.

    HIDDEN:   feature is not in the license or session is invalid —
              module should NOT be registered, panel should NOT appear.
    DISABLED: license includes the feature but binary is missing,
              download failed, or needs redownload —
              module SHOULD be registered, panel SHOULD appear grayed out.
    ENABLED:  license + binary + native auth all OK —
              module SHOULD be registered, panel fully functional.
    """

    HIDDEN = "hidden"
    DISABLED = "disabled"
    ENABLED = "enabled"


_HIDDEN_STATES = frozenset({"unactivated", "session_error", "unlicensed"})
_DISABLED_STATES = frozenset({"binary_missing", "download_failed", "needs_redownload"})
_ENABLED_STATES = frozenset({"ready", "session_warning"})


def get_feature_visibility(feature_id: str) -> FeatureVisibility:
    """Return the canonical visibility for a feature based on its effective state."""
    status = get_feature_status(feature_id)
    effective = status.get("effective_state", "")
    if effective in _ENABLED_STATES:
        return FeatureVisibility.ENABLED
    if effective in _DISABLED_STATES:
        return FeatureVisibility.DISABLED
    return FeatureVisibility.HIDDEN


def _all_feature_ids():
    return tuple(spec.feature_id for spec in iter_feature_specs())


def _empty_state():
    return {
        "features": {
            feature_id: {
                "last_download_failed": False,
                "last_download_error": "",
                "last_download_at": 0.0,
                "last_download_succeeded_at": 0.0,
            }
            for feature_id in _all_feature_ids()
        }
    }


_state_lock = threading.RLock()


def _load_persisted_state():
    with _state_lock:
        path = get_feature_status_path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                merged = _empty_state()
                merged.update(data)
                feature_data = merged.get("features", {})
                merged["features"] = {
                    feature_id: {
                        **_empty_state()["features"][feature_id],
                        **(feature_data.get(feature_id, {}) if isinstance(feature_data, dict) else {}),
                    }
                    for feature_id in _all_feature_ids()
                }
                return merged
        except FileNotFoundError:
            pass
        except Exception as exc:
            _log.debug("Failed to load feature status state: %s", exc)
        return _empty_state()


def _save_persisted_state(state):
    with _state_lock:
        path = get_feature_status_path()
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise


def _update_feature_state(feature_id, **updates):
    with _state_lock:
        state = _load_persisted_state()
        feature_state = dict(state["features"].get(feature_id, {}))
        feature_state.update(updates)
        state["features"][feature_id] = feature_state
        _save_persisted_state(state)
        return feature_state


def clear_feature_state():
    _save_persisted_state(_empty_state())


def _mark_download_success(feature_id):
    now = time.time()
    return _update_feature_state(
        feature_id,
        last_download_failed=False,
        last_download_error="",
        last_download_at=now,
        last_download_succeeded_at=now,
    )


def _mark_download_failure(feature_id, error):
    return _update_feature_state(
        feature_id,
        last_download_failed=True,
        last_download_error=str(error or "").strip(),
        last_download_at=time.time(),
    )


def get_feature_definition(feature_id):
    spec = get_feature_spec(feature_id)
    return {
        "label": spec.label,
        "module_name": spec.native_module_name,
        "feature_name": spec.feature_id,
    }


def _get_license_manager():
    from .manager import get_license_manager
    return get_license_manager()


def _get_license_snapshot():
    manager = _get_license_manager()
    status = manager.get_status()
    session = getattr(getattr(manager, "_client", None), "session", None)
    features = {}
    if bool(status.get("activated")):
        try:
            raw_features = manager.get_features()
        except Exception:
            raw_features = status.get("features", {}) or {}
        features = {
            str(name): bool(enabled)
            for name, enabled in dict(raw_features or {}).items()
        }
    elif session is not None:
        features = {
            str(name): bool(enabled)
            for name, enabled in dict(status.get("features", {}) or {}).items()
        }
    warning_levels = [str(item.get("level", "")) for item in status.get("warnings", [])]
    return {
        "status": status,
        "session": session,
        "features": features,
        "has_session": session is not None,
        "refresh_expired": bool(status.get("is_refresh_expired")),
        "warning_levels": warning_levels,
    }


def _get_binary_snapshot(feature_id):
    wrapper = get_native_wrapper(feature_id)
    wrapper.refresh_native_backend()
    load_state = wrapper.get_load_state()
    from ..native.loader import (
        get_primary_native_module_path,
        get_residual_native_module_paths,
        list_existing_native_module_paths,
    )

    spec = get_feature_spec(feature_id)
    primary_path = get_primary_native_module_path(spec.native_module_name)
    existing_paths = list_existing_native_module_paths(spec.native_module_name)
    residual_paths = get_residual_native_module_paths(spec.native_module_name)
    return {
        "wrapper": wrapper,
        "load_state": load_state,
        "binary_present": bool(existing_paths),
        "primary_path": primary_path,
        "existing_paths": existing_paths,
        "residual_paths": residual_paths,
    }


def _resolve_pre_native_effective_state(*, feature_id, license_snapshot, binary_snapshot):
    wrapper = binary_snapshot["wrapper"]
    status = license_snapshot["status"]
    entitled = bool(license_snapshot["features"].get(feature_id, False))
    warning_levels = set(license_snapshot["warning_levels"])

    if not license_snapshot["has_session"]:
        return "unactivated", "missing"
    if license_snapshot["refresh_expired"] or "ERROR" in warning_levels:
        return "session_error", "expired"
    if not entitled:
        return "unlicensed", "unlicensed"
    if not binary_snapshot["binary_present"]:
        return "binary_missing", "licensed"
    if binary_snapshot["residual_paths"]:
        return "needs_redownload", "licensed"
    if not wrapper.is_native_backend():
        return "needs_redownload", "licensed"
    if status.get("warnings"):
        return "session_warning", "warning"
    return "ready", "licensed"


def _build_message(*, label, effective_state, download_error=""):
    if effective_state == "unactivated":
        return f"{label} is locked. Activate your license in Addon Preferences."
    if effective_state == "unlicensed":
        return f"{label} is not included in your current license tier. Check Addon Preferences."
    if effective_state == "binary_missing":
        return f"{label} binary is missing. Download it in Addon Preferences."
    if effective_state == "needs_redownload":
        return f"{label} binary is outdated or incompatible with this addon version. Update the binary in Addon Preferences."
    if effective_state == "download_failed":
        if download_error:
            return f"{label} download failed: {download_error}. Retry from Addon Preferences."
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


def _build_post_download_error(*, label, status, had_loaded_backend=False):
    effective_state = str(status.get("effective_state", "") or "")
    detail = (
        str(status.get("native_reason", "") or "").strip()
        or str(status.get("load_error", "") or "").strip()
        or str(status.get("message", "") or "").strip()
    )
    if effective_state in {"ready", "session_warning"}:
        return ""
    if "integrity check failed" in detail.lower():
        message = f"{label} binary downloaded, but it does not match the installed addon source. Update the addon and native binary from the same build."
    elif effective_state == "needs_redownload":
        message = f"{label} binary downloaded, but validation still failed. Update the binary again after confirming the addon version matches."
    else:
        message = f"{label} binary downloaded, but it is still not ready."
    if detail:
        message = f"{message} {detail}"
    if had_loaded_backend:
        message = f"{message} Blender may still be holding a previously loaded native module in memory. Restart Blender before retrying."
    return message


def get_feature_status(feature_id):
    spec = get_feature_spec(feature_id)
    persisted_state = _load_persisted_state()["features"].get(feature_id, {})
    license_snapshot = _get_license_snapshot()
    binary_snapshot = _get_binary_snapshot(feature_id)
    wrapper = binary_snapshot["wrapper"]
    status = license_snapshot["status"]
    effective_state, license_state = _resolve_pre_native_effective_state(
        feature_id=feature_id,
        license_snapshot=license_snapshot,
        binary_snapshot=binary_snapshot,
    )
    if effective_state == "binary_missing" and persisted_state.get("last_download_failed"):
        effective_state = "download_failed"

    # ----------------------------------------------------------------
    # Native authorization check — the native module is the ultimate
    # authority.  Its set_license_state() has already been called
    # during licensing init / heartbeat, so get_license_status()
    # reflects the real HMAC-verified authorization.
    # ----------------------------------------------------------------
    _native_auth_reason = ""
    if effective_state in {"ready", "session_warning"}:
        if wrapper.is_native_backend():
            try:
                native_license = wrapper.get_license_status()
                if isinstance(native_license, dict) and native_license:
                    if not native_license.get("authorized", False):
                        effective_state = "needs_redownload"
                        license_state = "licensed"
                        _native_auth_reason = str(
                            native_license.get("reason", "") or ""
                        ).strip()
            except Exception:
                pass

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

    if effective_state == "needs_redownload" and _native_auth_reason:
        message = f"{spec.label} binary verification failed: {_native_auth_reason}. Download the correct binary in Addon Preferences."
    elif effective_state == "needs_redownload" and binary_snapshot["residual_paths"]:
        message = f"{spec.label} has leftover or duplicate native binaries. Update the binary in Addon Preferences."
    else:
        message = _build_message(
            label=spec.label,
            effective_state=effective_state,
            download_error=persisted_state.get("last_download_error", ""),
        )

    return {
        "feature_name": feature_id,
        "label": spec.label,
        "module_name": spec.native_module_name,
        "license_state": license_state,
        "binary_state": binary_state,
        "native_state": native_state,
        "effective_state": effective_state,
        "message": message,
        "action": _build_action(effective_state),
        "can_download": effective_state in {"binary_missing", "needs_redownload", "download_failed"},
        "can_retry": effective_state in {"needs_redownload", "download_failed"},
        "download_error": persisted_state.get("last_download_error", ""),
        "native_reason": _native_auth_reason,
        "warnings": list(status.get("warnings", [])),
        "module_path": binary_snapshot["load_state"].get("module_path", ""),
        "load_error": binary_snapshot["load_state"].get("error", ""),
        "primary_module_path": binary_snapshot["primary_path"],
        "existing_module_paths": binary_snapshot["existing_paths"],
        "residual_module_paths": binary_snapshot["residual_paths"],
    }


def get_all_feature_statuses():
    return {feature_id: get_feature_status(feature_id) for feature_id in _all_feature_ids()}


def is_feature_ready(feature_id):
    return get_feature_status(feature_id)["effective_state"] in {"ready", "session_warning"}


def is_feature_ready_for_native_sync(feature_id):
    license_snapshot = _get_license_snapshot()
    binary_snapshot = _get_binary_snapshot(feature_id)
    effective_state, _license_state = _resolve_pre_native_effective_state(
        feature_id=feature_id,
        license_snapshot=license_snapshot,
        binary_snapshot=binary_snapshot,
    )
    return effective_state in {"ready", "session_warning"}


def get_feature_action_hint(feature_id):
    return get_feature_status(feature_id)["message"]


def refresh_feature_runtime(feature_id=None):
    feature_ids = [feature_id] if feature_id else list(_all_feature_ids())
    refreshed = {}
    for current_feature in feature_ids:
        wrapper = get_native_wrapper(current_feature)
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

    try:
        from ..feature_registration import reconcile_feature_modules

        reconcile_feature_modules()
    except Exception as exc:
        _log.debug("Failed to reconcile feature modules: %s", exc)

    return refreshed


def download_feature_binary(feature_id, force=False):
    from ..native.downloader import ensure_native_binary

    spec = get_feature_spec(feature_id)
    pre_status = get_feature_status(feature_id)
    had_loaded_backend = bool(pre_status.get("module_path"))
    try:
        ok = ensure_native_binary(spec.download_module_name, force=force)
        if not ok:
            _mark_download_failure(feature_id, "Download not available for this feature.")
            return {"ok": False, "feature_name": feature_id, "error": "Download not available for this feature."}
        refresh_feature_runtime(feature_id)
        post_status = get_feature_status(feature_id)
        post_error = _build_post_download_error(label=spec.label, status=post_status, had_loaded_backend=had_loaded_backend)
        if post_error:
            _mark_download_failure(feature_id, post_error)
            return {"ok": False, "feature_name": feature_id, "error": post_error}
        _mark_download_success(feature_id)
        return {"ok": True, "feature_name": feature_id, "error": ""}
    except Exception as exc:
        _mark_download_failure(feature_id, exc)
        refresh_feature_runtime(feature_id)
        return {"ok": False, "feature_name": feature_id, "error": str(exc)}


def activate_and_prepare_features(license_key):
    manager = _get_license_manager()
    session = manager.activate(license_key)
    clear_feature_state()
    download_results = {}
    licensed_features = [
        spec.feature_id
        for spec in iter_feature_specs()
        if bool(getattr(session, "features", {}).get(spec.feature_id, False))
    ]
    for feature_id in licensed_features:
        download_results[feature_id] = download_feature_binary(feature_id)
    refresh_feature_runtime()
    return {
        "session": session,
        "licensed_features": licensed_features,
        "download_results": download_results,
        "download_labels": {
            spec.feature_id: spec.label
            for spec in iter_feature_specs()
            if spec.feature_id in licensed_features
        },
    }
