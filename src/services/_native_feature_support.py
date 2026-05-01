import hashlib
import logging
import os


def get_feature_status(feature_name):
    from ..licensing.feature_access import get_feature_status as _get_feature_status

    return _get_feature_status(feature_name)


def is_license_activated():
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_activated()
    except Exception:
        return False


def is_feature_licensed(feature_name):
    try:
        from ..licensing.manager import get_license_manager
        return get_license_manager().is_feature_licensed(feature_name)
    except Exception:
        return False


def verify_source_integrity(verify_func):
    """Compute hashes of critical Python files and pass them to native code."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    files = {
        "face_cap_service.py": os.path.join(base_dir, "services", "face_cap_service.py"),
        "miframes_service.py": os.path.join(base_dir, "services", "miframes_service.py"),
        "manager.py": os.path.join(base_dir, "licensing", "manager.py"),
    }

    hashes = {}
    for name, path in files.items():
        try:
            with open(path, "rb") as handle:
                hashes[name] = hashlib.sha256(handle.read()).hexdigest()
        except Exception:
            hashes[name] = ""

    try:
        verify_func(hashes)
    except Exception:
        pass


def get_feature_lock_reason(*, feature_label, binary_available, binary_lock_reason, feature_name):
    status = get_feature_status(feature_name)
    return status.get("message") or f"{feature_label} is not unlocked."


def sync_license_state_to_native(
    *,
    logger: logging.Logger,
    backend_label,
    feature_unlocked,
    compute_proof,
    set_license_state,
    verify_func,
):
    """Propagate the current license state to a native backend."""
    try:
        from ..licensing.manager import get_license_manager

        manager = get_license_manager()
        device_id = manager.get_device_id()
        verify_source_integrity(verify_func)

        if feature_unlocked():
            expires_at, hmac_proof = compute_proof(device_id)
            set_license_state(device_id, expires_at, hmac_proof)
        else:
            set_license_state(device_id, 0, "invalid")
    except Exception as exc:
        logger.debug("Failed to sync license to native %s: %s", backend_label, exc)
