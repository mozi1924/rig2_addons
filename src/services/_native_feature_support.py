import logging
import os

_NATIVE_GRANT_REFRESH_REASON_MARKERS = (
    "digest mismatch",
    "size mismatch",
    "artifact manifest",
    "manifest mismatch",
    "module mismatch",
    "feature mismatch",
    "binary validation failed",
    "native binary path is unavailable",
    "native grant missing artifact manifest",
    "native grant missing python manifest",
    "artifact manifest is incomplete",
    "authorization state is unavailable",
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
    return bool(status.get("needs_redownload", False))


def native_reason_allows_grant_refresh(reason):
    detail = str(reason or "").strip().lower()
    if not detail:
        return False
    return any(marker in detail for marker in _NATIVE_GRANT_REFRESH_REASON_MARKERS)


def get_native_failure_reason(get_license_status):
    if not callable(get_license_status):
        return ""
    try:
        status = get_license_status() or {}
    except Exception:
        return ""
    if not isinstance(status, dict):
        return ""
    if status.get("authorized", False):
        return ""
    return str(status.get("reason", "") or "").strip()


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
    allow_network=True,
):
    """Propagate the current license state to a native backend."""
    def _clear_with_reason(message: str):
        try:
            clear_license_state(str(message or "").strip())
        except TypeError:
            clear_license_state()

    try:
        from ..licensing.manager import get_license_manager

        manager = get_license_manager()

        if is_feature_ready_for_native(feature_id):
            current_reason = get_native_failure_reason(get_license_status)
            if current_reason and not native_reason_allows_grant_refresh(current_reason):
                return
            trust_bundle_token = manager.get_trust_bundle_token(allow_network=allow_network)
            grant = None
            if allow_network:
                try:
                    grant = manager.request_native_grant(feature_id)
                except Exception:
                    grant = manager.get_cached_native_grant(feature_id)
            else:
                grant = manager.get_cached_native_grant(feature_id)
            if grant is None:
                _clear_with_reason("Native grant unavailable. Activate or re-sync your license.")
                return
            apply_grant(
                grant.grant_token,
                trust_bundle_token,
                get_addon_source_root(),
            )
        else:
            _clear_with_reason("Native feature is not ready for authorization yet.")
    except Exception as exc:
        _clear_with_reason(f"Native grant sync failed: {exc}")
        logger.debug("Failed to sync license to native %s: %s", feature_id, exc)


def is_feature_ready_for_native(feature_name):
    from ..licensing.feature_access import is_feature_ready_for_native_sync

    return is_feature_ready_for_native_sync(feature_name)
