import logging

from .manager import LicenseManager, get_license_manager
from .config import HEARTBEAT_INTERVAL_SECONDS

_log = logging.getLogger(__name__)

__all__ = [
    "LicenseManager",
    "get_license_manager",
]

_HEARTBEAT_TIMER_ACTIVE = False


def _heartbeat_timer():
    """Blender timer callback — sends heartbeat and reschedules itself."""
    global _HEARTBEAT_TIMER_ACTIVE
    if not _HEARTBEAT_TIMER_ACTIVE:
        return  # timer was cancelled

    try:
        get_license_manager().heartbeat()
    except Exception:
        pass  # heartbeat is best-effort

    return HEARTBEAT_INTERVAL_SECONDS


def register():
    """Eagerly initialize the license manager and start the heartbeat timer."""
    global _HEARTBEAT_TIMER_ACTIVE

    try:
        get_license_manager()
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
