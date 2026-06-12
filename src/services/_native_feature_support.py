"""Native feature support — open-source build, no license checks required."""
import os


def get_feature_status(feature_name):
    return {"effective_state": "ready", "message": "Ready."}


def is_feature_licensed(feature_name):
    return True


def get_addon_source_root():
    return os.path.dirname(os.path.dirname(__file__))


def native_integrity_failed(get_license_status):
    return False


def native_reason_allows_grant_refresh(reason):
    return False


def native_reason_requires_redownload(reason):
    return False


def native_reason_is_session_sync_issue(reason):
    return False


def get_native_failure_reason(get_license_status):
    return ""


def get_feature_lock_reason(*, feature_label, binary_available, binary_lock_reason, feature_name):
    return ""


def sync_license_state_to_native(
    *,
    logger,
    feature_id,
    apply_grant=None,
    clear_license_state=None,
    get_license_status=None,
    allow_network=True,
):
    pass


def is_feature_ready_for_native(feature_name):
    return True
