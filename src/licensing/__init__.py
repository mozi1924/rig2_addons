import logging

from .manager import LicenseManager, get_license_manager
from .config import HEARTBEAT_INTERVAL_SECONDS

_log = logging.getLogger(__name__)

__all__ = [
    "LicenseManager",
    "get_license_manager",
    "sync_license_to_native_modules",
]

_HEARTBEAT_TIMER_ACTIVE = False


def sync_license_to_native_modules():
    """Propagate the current license state to all native C++ modules."""
    try:
        from ..services.face_cap_service import get_face_cap_backend_service
        get_face_cap_backend_service().sync_license_to_native()
    except Exception as exc:
        _log.debug("sync face_cap license: %s", exc)

    try:
        from ..services.miframes_service import get_miframes_backend_service
        get_miframes_backend_service().sync_license_to_native()
    except Exception as exc:
        _log.debug("sync miframes license: %s", exc)


def _heartbeat_timer():
    """Blender timer callback — sends heartbeat and reschedules itself."""
    global _HEARTBEAT_TIMER_ACTIVE
    if not _HEARTBEAT_TIMER_ACTIVE:
        return  # timer was cancelled

    mgr = get_license_manager()
    try:
        mgr.heartbeat()
    except Exception:
        pass  # heartbeat is best-effort

    # After heartbeat, refresh the native module license state.
    # This keeps the HMAC proofs current.
    try:
        if mgr.is_activated():
            sync_license_to_native_modules()
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

    return HEARTBEAT_INTERVAL_SECONDS


def register():
    """Eagerly initialize the license manager and start the heartbeat timer."""
    global _HEARTBEAT_TIMER_ACTIVE

    try:
        get_license_manager()
        # Sync any existing session to native modules on startup.
        sync_license_to_native_modules()
    except Exception as exc:
        _log.warning("License manager init failed (non-fatal): %s", exc)

    try:
        import bpy
        if not _HEARTBEAT_TIMER_ACTIVE:
            _HEARTBEAT_TIMER_ACTIVE = True
            bpy.app.timers.register(_heartbeat_timer, first_interval=HEARTBEAT_INTERVAL_SECONDS)
    except Exception:
        pass


def unregister():
    """Stop the heartbeat timer. Session persists across disable/enable cycles."""
    global _HEARTBEAT_TIMER_ACTIVE
    _HEARTBEAT_TIMER_ACTIVE = False

    try:
        import bpy
        if bpy.app.timers.is_registered(_heartbeat_timer):
            bpy.app.timers.unregister(_heartbeat_timer)
    except Exception:
        pass
