import hashlib
import logging
import os

from ..licensing._hmac_proof import compute_feature_proof
from ..licensing.registry import get_feature_spec

def get_feature_status(feature_name):
    from ..licensing.feature_access import get_feature_status as _get_feature_status

    return _get_feature_status(feature_name)


def is_feature_licensed(feature_name):
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_feature_licensed(feature_name)
    except Exception:
        return False


def verify_source_integrity(feature_name, verify_func):
    """Compute registered source hashes for a feature and pass them to native code."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    spec = get_feature_spec(feature_name)
    hashes = {}
    for name, relative_path in spec.integrity_targets:
        path = os.path.join(base_dir, relative_path)
        try:
            with open(path, "rb") as handle:
                hashes[name] = hashlib.sha256(handle.read()).hexdigest()
        except Exception:
            hashes[name] = ""

    verify_func(hashes)


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


def get_feature_lock_reason(*, feature_label, binary_available, binary_lock_reason, feature_name):
    status = get_feature_status(feature_name)
    return status.get("message") or f"{feature_label} is not unlocked."


def sync_license_state_to_native(
    *,
    logger: logging.Logger,
    feature_id,
    set_license_state,
    verify_func,
    get_license_status=None,
):
    """Propagate the current license state to a native backend."""
    try:
        from ..licensing.manager import get_license_manager

        manager = get_license_manager()
        device_id = manager.get_device_id()
        verify_source_integrity(feature_id, verify_func)
        if native_integrity_failed(get_license_status):
            logger.debug("Native integrity validation failed for %s; not applying license state.", feature_id)
            return

        if is_feature_ready_for_native(feature_id):
            expires_at, hmac_proof = compute_feature_proof(feature_id, device_id)
            set_license_state(device_id, expires_at, hmac_proof)
        else:
            set_license_state(device_id, 0, "invalid")
    except Exception as exc:
        try:
            set_license_state("", 0, "invalid")
        except Exception:
            pass
        logger.debug("Failed to sync license to native %s: %s", feature_id, exc)


def is_feature_ready_for_native(feature_name):
    from ..licensing.feature_access import is_feature_ready_for_native_sync

    return is_feature_ready_for_native_sync(feature_name)
