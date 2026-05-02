import logging
import threading

from .manager import LicenseManager, get_license_manager
from .config import HEARTBEAT_INTERVAL_SECONDS
from .registry import iter_feature_specs
from .runtime_refresh import refresh_runtime_bindings

_log = logging.getLogger(__name__)

__all__ = [
    "LicenseManager",
    "get_license_manager",
    "is_runtime_ready",
    "sync_license_to_native_modules",
    "process_pending_native_sync",
]

_HEARTBEAT_TIMER_ACTIVE = False
_FAST_HEARTBEAT_POLL_SECONDS = 1.0
_LICENSE_RUNTIME_READY = False
_ASYNC_NATIVE_SYNC_LOCK = threading.Lock()
_ASYNC_NATIVE_SYNC_IN_FLIGHT = False
_ASYNC_NATIVE_SYNC_RESULT_PENDING = False
_ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = False
_MAIN_THREAD_NATIVE_SYNC_PENDING = False
_MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = False


def is_runtime_ready():
    """Return whether the Rig2 licensing runtime finished registration."""
    return _LICENSE_RUNTIME_READY


def sync_license_to_native_modules(*, allow_network=True):
    """Propagate the current license state to all native C++ modules."""
    from ..services.registry import get_feature_service

    for spec in iter_feature_specs():
        try:
            get_feature_service(spec.feature_id).sync_license_to_native(
                allow_network=allow_network,
            )
        except Exception as exc:
            _log.debug("sync %s license: %s", spec.feature_id, exc)


def _request_async_native_sync(*, prewarm_verification=False, refresh_runtime=False):
    global _ASYNC_NATIVE_SYNC_IN_FLIGHT, _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING

    with _ASYNC_NATIVE_SYNC_LOCK:
        if _ASYNC_NATIVE_SYNC_IN_FLIGHT:
            _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = (
                _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING or refresh_runtime
            )
            return False
        _ASYNC_NATIVE_SYNC_IN_FLIGHT = True
        _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = refresh_runtime

    def _worker():
        global _ASYNC_NATIVE_SYNC_IN_FLIGHT, _ASYNC_NATIVE_SYNC_RESULT_PENDING
        try:
            mgr = get_license_manager()
            if mgr._client.session is not None:
                mgr.prepare_native_sync_material(
                    prewarm_verification=prewarm_verification,
                    allow_network=True,
                )
        except Exception as exc:
            _log.debug("Async native sync failed: %s", exc)
        finally:
            with _ASYNC_NATIVE_SYNC_LOCK:
                _ASYNC_NATIVE_SYNC_IN_FLIGHT = False
                _ASYNC_NATIVE_SYNC_RESULT_PENDING = True

    thread = threading.Thread(
        target=_worker,
        name="Rig2AsyncNativeSync",
        daemon=True,
    )
    try:
        thread.start()
        return True
    except Exception:
        with _ASYNC_NATIVE_SYNC_LOCK:
            _ASYNC_NATIVE_SYNC_IN_FLIGHT = False
        raise


def _consume_async_native_sync_result():
    global _ASYNC_NATIVE_SYNC_RESULT_PENDING, _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING
    with _ASYNC_NATIVE_SYNC_LOCK:
        if not _ASYNC_NATIVE_SYNC_RESULT_PENDING:
            return None
        refresh_runtime = _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING
        _ASYNC_NATIVE_SYNC_RESULT_PENDING = False
        _ASYNC_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = False
    return {
        "refresh_runtime": refresh_runtime,
    }


def process_pending_native_sync():
    """Apply pending native grants on Blender main thread using cached material."""
    global _MAIN_THREAD_NATIVE_SYNC_PENDING, _MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING

    async_result = _consume_async_native_sync_result()
    if async_result is not None:
        _MAIN_THREAD_NATIVE_SYNC_PENDING = True
        _MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = (
            _MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING
            or bool(async_result.get("refresh_runtime"))
        )

    mgr = get_license_manager()
    if not _MAIN_THREAD_NATIVE_SYNC_PENDING:
        return False
    if mgr._client.session is None:
        _MAIN_THREAD_NATIVE_SYNC_PENDING = False
        _MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = False
        return False

    sync_license_to_native_modules(allow_network=False)
    refresh_runtime = bool(_MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING)
    _MAIN_THREAD_NATIVE_SYNC_PENDING = False
    _MAIN_THREAD_NATIVE_SYNC_REFRESH_RUNTIME_PENDING = False
    if refresh_runtime:
        refresh_runtime_bindings(logger=_log)
    return True


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
        process_pending_native_sync()

        actions = mgr.pop_post_heartbeat_actions()
        if actions.get("sync_native") and mgr._client.session is not None:
            _request_async_native_sync(
                refresh_runtime=bool(actions.get("refresh_runtime")),
            )
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
        # Do not block Blender startup on native grant / JWKS network requests.
        # Kick off startup sync in a background thread instead.
        if mgr._client.session is not None:
            _request_async_native_sync(prewarm_verification=True)
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
