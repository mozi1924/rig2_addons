import logging

from .manager import LicenseManager, get_license_manager
from .config import HEARTBEAT_INTERVAL_SECONDS
from .registry import iter_feature_specs

_log = logging.getLogger(__name__)

__all__ = [
    "LicenseManager",
    "get_license_manager",
    "is_runtime_ready",
    "sync_license_to_native_modules",
]

_HEARTBEAT_TIMER_ACTIVE = False
_FAST_HEARTBEAT_POLL_SECONDS = 1.0
_LICENSE_RUNTIME_READY = False


def is_runtime_ready():
    """Return whether the Rig2 licensing runtime finished registration."""
    return _LICENSE_RUNTIME_READY


def sync_license_to_native_modules():
    """Propagate the current license state to all native C++ modules."""
    from ..services.registry import get_feature_service

    for spec in iter_feature_specs():
        try:
            get_feature_service(spec.feature_id).sync_license_to_native()
        except Exception as exc:
            _log.debug("sync %s license: %s", spec.feature_id, exc)


def _heartbeat_timer():
    """Blender timer callback — sends heartbeat and reschedules itself."""
    global _HEARTBEAT_TIMER_ACTIVE
    if not _HEARTBEAT_TIMER_ACTIVE:
        return  # timer was cancelled

    mgr = get_license_manager()
    heartbeat_result = None
    try:
        heartbeat_result = mgr.consume_heartbeat_result()
    except Exception:
        heartbeat_result = None

    try:
        actions = mgr.pop_post_heartbeat_actions()
        if actions.get("sync_native") and mgr._client.session is not None:
            sync_license_to_native_modules()
        if actions.get("refresh_runtime"):
            from .feature_access import refresh_feature_runtime

            refresh_feature_runtime()
    except Exception:
        pass

    try:
        if mgr.should_trigger_immediate_heartbeat():
            mgr.request_heartbeat(reason="timer_overdue")
    except Exception:
        pass

    # Stop the timer if the refresh token has expired.
    try:
        status = mgr.get_status()
        if status.get("is_refresh_expired"):
            _log.warning("Refresh token expired, stopping heartbeat timer.")
            return None
    except Exception:
        pass

    if heartbeat_result is not None:
        return _FAST_HEARTBEAT_POLL_SECONDS
    if mgr.is_heartbeat_in_flight():
        return _FAST_HEARTBEAT_POLL_SECONDS
    try:
        if mgr.should_trigger_immediate_heartbeat():
            return _FAST_HEARTBEAT_POLL_SECONDS
    except Exception:
        pass
    return HEARTBEAT_INTERVAL_SECONDS


def register():
    """Eagerly initialize the license manager and start the heartbeat timer."""
    global _HEARTBEAT_TIMER_ACTIVE, _LICENSE_RUNTIME_READY
    mgr = None

    try:
        mgr = get_license_manager()
        # Sync any existing session to native modules on startup.
        sync_license_to_native_modules()
        if mgr.should_trigger_immediate_heartbeat():
            mgr.request_heartbeat(reason="register_overdue")
        _LICENSE_RUNTIME_READY = True
    except Exception as exc:
        _LICENSE_RUNTIME_READY = False
        _log.warning("License manager init failed (non-fatal): %s", exc)

    try:
        import bpy
        if not _HEARTBEAT_TIMER_ACTIVE:
            _HEARTBEAT_TIMER_ACTIVE = True
            first_interval = _FAST_HEARTBEAT_POLL_SECONDS
            try:
                if not mgr.should_trigger_immediate_heartbeat():
                    first_interval = HEARTBEAT_INTERVAL_SECONDS
            except Exception:
                first_interval = HEARTBEAT_INTERVAL_SECONDS
            bpy.app.timers.register(_heartbeat_timer, first_interval=first_interval)
    except Exception:
        pass


def unregister():
    """Stop the heartbeat timer. Session persists across disable/enable cycles."""
    global _HEARTBEAT_TIMER_ACTIVE, _LICENSE_RUNTIME_READY
    _HEARTBEAT_TIMER_ACTIVE = False
    _LICENSE_RUNTIME_READY = False

    try:
        import bpy
        if bpy.app.timers.is_registered(_heartbeat_timer):
            bpy.app.timers.unregister(_heartbeat_timer)
    except Exception:
        pass
