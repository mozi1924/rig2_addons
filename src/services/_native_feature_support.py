import json
import logging
import os

from ..orbisauth._jwt import fetch_jwks


_NATIVE_REDOWNLOAD_REASON_MARKERS = (
    "integrity check failed",
    "digest mismatch",
    "size mismatch",
    "artifact manifest",
    "manifest mismatch",
    "module mismatch",
    "binary validation failed",
    "source root not found",
    "missing file",
)

def get_feature_status(feature_name):
    from ..licensing.feature_access import get_feature_status as _get_feature_status

    return _get_feature_status(feature_name)


def is_feature_licensed(feature_name):
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_feature_licensed(feature_name)
    except Exception:
        return False


def get_addon_source_root():
    return os.path.dirname(os.path.dirname(__file__))


def native_integrity_failed(get_license_status):
    if not callable(get_license_status):
        return False
    try:
        status = get_license_status() or {}
    except Exception:
        return False
    if not isinstance(status, dict):
        return False
    if status.get("authorized", False):
        return False
    reason = str(status.get("reason", "") or "").lower()
    return "integrity check failed" in reason


def native_reason_requires_redownload(reason):
    detail = str(reason or "").strip().lower()
    if not detail:
        return False
    return any(marker in detail for marker in _NATIVE_REDOWNLOAD_REASON_MARKERS)


def get_feature_lock_reason(*, feature_label, binary_available, binary_lock_reason, feature_name):
    status = get_feature_status(feature_name)
    return status.get("message") or f"{feature_label} is not unlocked."


def sync_license_state_to_native(
    *,
    logger: logging.Logger,
    feature_id,
    apply_grant,
    clear_license_state,
    get_license_status=None,
):
    """Propagate the current license state to a native backend."""
    try:
        from ..licensing.manager import get_license_manager

        manager = get_license_manager()
        if native_integrity_failed(get_license_status):
            logger.debug("Native integrity validation failed for %s; not applying license state.", feature_id)
            return

        if is_feature_ready_for_native(feature_id):
            grant = manager.request_native_grant(feature_id)
            if grant is None:
                clear_license_state()
                return
            jwks = fetch_jwks(manager._client.server_url, timeout=manager._client.timeout_seconds)
            apply_grant(
                grant.grant_token,
                json.dumps(jwks, sort_keys=True),
                get_addon_source_root(),
            )
        else:
            clear_license_state()
    except Exception as exc:
        try:
            clear_license_state()
        except Exception:
            pass
        logger.debug("Failed to sync license to native %s: %s", feature_id, exc)


def is_feature_ready_for_native(feature_name):
    from ..licensing.feature_access import is_feature_ready_for_native_sync

    return is_feature_ready_for_native_sync(feature_name)
