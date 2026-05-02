import logging
import platform
import threading
import time

from ..orbisauth import OrbisAuthClient, OrbisAuthError, OrbisAuthTokenError
from ..orbisauth._jwt import get_token_expiry
from ..orbisauth._client import NativeGrantInfo
from .config import (
    DEFAULT_SERVER_URL,
    HTTP_TIMEOUT_SECONDS,
    REFRESH_SKEW_SECONDS,
)
from .device_id import get_or_create_device_id
from .paths import get_native_grant_cache_path, get_session_path, get_trust_bundle_path
from .runtime_cache import (
    CachedNativeGrant,
    clear_cached_native_grants,
    clear_cached_trust_bundle,
    load_cached_native_grants,
    load_cached_trust_bundle,
    save_cached_native_grant,
)

_log = logging.getLogger(__name__)
_SESSION_EXPIRY_WARNING_SECONDS = 3600
_SESSION_EXPIRY_CRITICAL_SECONDS = 300


def _generate_device_name():
    """Generate a human-readable device name."""
    try:
        import socket
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    system = platform.system() or "Unknown"
    return f"{host} ({system})"


class LicenseManager:
    """Manages Orbisauth license activation and feature gating for Rig2.

    Lifecycle:
    1. On addon load, try to load a persisted session from disk.
    2. User activates via addon preferences with a license key.
    3. Features are gated on: binary exists + license is valid + feature flag set.
    4. Heartbeat runs periodically to keep the session alive.
    """

    def __init__(self):
        self._device_id = get_or_create_device_id()
        self._device_name = _generate_device_name()
        self._heartbeat_lock = threading.RLock()
        self._reset_heartbeat_tracking()
        session_path = get_session_path()
        self._trust_bundle_path = get_trust_bundle_path()
        self._native_grant_cache_path = get_native_grant_cache_path()
        self._client = OrbisAuthClient(
            server_url=DEFAULT_SERVER_URL,
            session_path=session_path,
            auto_refresh=True,
            refresh_skew_seconds=REFRESH_SKEW_SECONDS,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
            trust_bundle_path=self._trust_bundle_path,
        )
        self._load_existing_session()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _reset_heartbeat_tracking(self, *, now: float = 0.0):
        self._last_heartbeat_time = now
        self._last_heartbeat_attempt_time = now
        self._consecutive_heartbeat_failures = 0
        self._last_heartbeat_error = ""
        with self._heartbeat_lock:
            self._heartbeat_thread = None
            self._heartbeat_in_flight = False
            self._heartbeat_result_pending = None
            self._native_sync_pending = False
            self._runtime_refresh_pending = False

    def _safe_token_expiry(self, token, fallback_expiry):
        try:
            return get_token_expiry(token)
        except Exception:
            return fallback_expiry

    def _verified_features(self):
        if self._client.session is None:
            return {}
        try:
            getter = getattr(self._client, "get_features_no_network", None)
            if callable(getter):
                return getter()
            return self._client.get_features()
        except (OrbisAuthTokenError, OrbisAuthError):
            return {}

    def _has_verified_session(self):
        if self._client.session is None:
            return False
        try:
            getter = getattr(self._client, "get_features_no_network", None)
            if callable(getter):
                getter()
            else:
                self._client.get_features()
            return True
        except (OrbisAuthTokenError, OrbisAuthError):
            return False

    def warm_verification_cache(self):
        """Warm the JWKS/token verification cache off the main thread."""
        if self._client.session is None:
            return {}
        try:
            return self._client.get_features()
        except (OrbisAuthTokenError, OrbisAuthError):
            return {}

    def _build_inactive_status(self):
        return {
            "activated": False,
            "product": "",
            "tier": "",
            "license_id": "",
            "device_name": "",
            "device_id": self._device_id,
            "features": {},
            "access_token_expires_at": 0,
            "access_token_expires_in_seconds": 0,
            "refresh_token_expires_at": 0,
            "offline_valid_until": 0,
            "offline_valid_remaining_seconds": 0,
            "session_valid_until": 0,
            "session_valid_remaining_seconds": 0,
            "session_activated_at": 0.0,
            "last_heartbeat_at": self._last_heartbeat_time,
            "last_heartbeat_attempt_at": self._last_heartbeat_attempt_time,
            "last_heartbeat_error": self._last_heartbeat_error,
            "consecutive_heartbeat_failures": self._consecutive_heartbeat_failures,
            "is_access_expired": True,
            "is_refresh_expired": True,
            "needs_heartbeat": False,
            "should_auto_heartbeat_now": False,
            "heartbeat_in_flight": False,
            "heartbeat_interval": 0,
            "heartbeat_grace": 0,
            "heartbeat_due_at": 0,
            "heartbeat_overdue_seconds": 0,
            "warnings": [],
        }

    def _build_status_warnings(
        self,
        *,
        is_valid,
        is_refresh_expired,
        is_access_expired,
        access_expires_in,
        needs_heartbeat,
        heartbeat_in_flight,
        should_auto_heartbeat_now,
    ):
        warnings = []
        if heartbeat_in_flight and not is_refresh_expired:
            warnings.append({
                "level": "INFO",
                "message": "License heartbeat is syncing in the background.",
                "action_required": False,
            })
        elif should_auto_heartbeat_now:
            warnings.append({
                "level": "WARNING",
                "message": (
                    "License heartbeat is overdue. Rig2 has started a background sync attempt."
                ),
                "action_required": False,
            })

        if is_valid and not is_refresh_expired:
            if (
                0 < access_expires_in <= _SESSION_EXPIRY_WARNING_SECONDS
                and needs_heartbeat
                and not heartbeat_in_flight
            ):
                warnings.append({
                    "level": "WARNING",
                    "message": (
                        f"License session expires in {int(access_expires_in // 60)} minutes. "
                        "Connect to the internet to refresh."
                    ),
                    "action_required": True,
                })
            elif access_expires_in <= _SESSION_EXPIRY_CRITICAL_SECONDS and not is_access_expired:
                warnings.append({
                    "level": "CRITICAL",
                    "message": (
                        f"License session expires in {int(access_expires_in // 60)} minutes. "
                        "Please connect to the internet immediately."
                    ),
                    "action_required": True,
                })

        if is_access_expired and not is_refresh_expired:
            warnings.append({
                "level": "WARNING",
                "message": (
                    "Offline license access has expired. Rig2 will refresh it in the background "
                    "when possible, or you can use Sync Now."
                ),
                "action_required": True,
            })

        if is_refresh_expired:
            warnings.append({
                "level": "ERROR",
                "message": "License session has expired. Please re-activate your license.",
                "action_required": True,
            })

        if self._consecutive_heartbeat_failures >= 3 and not is_refresh_expired:
            warnings.append({
                "level": "WARNING",
                "message": (
                    f"Unable to reach license server ({self._consecutive_heartbeat_failures} "
                    "failed attempts). Check your internet connection."
                ),
                "action_required": True,
            })
        elif self._last_heartbeat_error and not heartbeat_in_flight and not is_refresh_expired:
            warnings.append({
                "level": "WARNING",
                "message": f"Last heartbeat attempt failed: {self._last_heartbeat_error}",
                "action_required": False,
            })
        return warnings

    def _record_heartbeat_success(self, *, completed_at=None, refresh_runtime=False):
        self._last_heartbeat_time = float(completed_at or time.time())
        self._consecutive_heartbeat_failures = 0
        self._last_heartbeat_error = ""
        with self._heartbeat_lock:
            self._native_sync_pending = True
            if refresh_runtime:
                self._runtime_refresh_pending = True

    def _record_heartbeat_failure(self, error):
        self._consecutive_heartbeat_failures += 1
        self._last_heartbeat_error = str(error or "")

    def _load_existing_session(self):
        """Try to load a previously persisted session."""
        try:
            session = self._client.load_session()
            if session is not None:
                _log.info(
                    "Loaded license session: product=%s tier=%s device=%s",
                    session.product,
                    session.tier,
                    session.device_id,
                )
                if session.device_id and session.device_id != self._device_id:
                    _log.warning(
                        "Session device_id %s differs from current device_id %s",
                        session.device_id,
                        self._device_id,
                    )
                self._reset_heartbeat_tracking(now=time.time())
        except Exception as exc:
            _log.warning("Failed to load license session: %s", exc)

    def activate(self, license_key):
        """Activate a license key on this device.

        Returns the Session on success.

        Raises:
            OrbisAuthError: if activation fails
        """
        session = self._client.activate(
            license_key=license_key,
            device_id=self._device_id,
            device_name=self._device_name,
        )
        self._reset_heartbeat_tracking(now=time.time())
        _log.info(
            "License activated: product=%s tier=%s license=%s",
            session.product,
            session.tier,
            session.license_id,
        )
        return session

    def deactivate(self):
        """Deactivate the current session and clear persisted data."""
        self._client.deactivate()
        self._reset_heartbeat_tracking()
        clear_cached_trust_bundle(self._trust_bundle_path)
        clear_cached_native_grants(self._native_grant_cache_path)
        try:
            from .feature_access import clear_feature_state

            clear_feature_state()
        except Exception:
            pass
        _log.info("License deactivated.")

    # ------------------------------------------------------------------
    # Feature gating
    # ------------------------------------------------------------------

    def is_activated(self):
        """Check if a valid license session exists (offline check)."""
        return self._has_verified_session()

    def is_feature_licensed(self, feature_name):
        """Check if a specific feature is licensed.

        Performs local JWT verification — no server call.
        Returns False if the session is invalid or the feature is not in the token.
        """
        features = self._verified_features()
        if not features:
            return False
        return bool(features.get(feature_name, False))

    def get_features(self):
        """Return the features dict from the current license (offline check)."""
        return self._verified_features()

    # ------------------------------------------------------------------
    # Status & UI helpers
    # ------------------------------------------------------------------

    def get_device_id(self):
        """Return the current device ID."""
        return self._device_id

    def get_status(self):
        """Return a dict describing the current license state for UI display."""
        self.consume_heartbeat_result()
        session = self._client.session
        if session is None:
            return self._build_inactive_status()

        now = time.time()
        access_exp = self._safe_token_expiry(session.tokens.access_token, 0)
        offline_exp = self._safe_token_expiry(
            session.tokens.offline_token,
            session.activated_at + getattr(session.tokens, "offline_expires_in", session.tokens.expires_in),
        )
        refresh_exp = self._safe_token_expiry(
            session.tokens.refresh_token,
            session.activated_at + session.tokens.refresh_expires_in,
        )

        is_valid = self.is_activated()
        access_expires_in = max(0, access_exp - now) if access_exp else 0
        offline_expires_in = max(0, offline_exp - now) if offline_exp else 0
        is_access_expired = offline_exp > 0 and now >= offline_exp
        is_refresh_expired = refresh_exp > 0 and now >= refresh_exp
        offline_valid_until = int(offline_exp) if offline_exp else 0
        session_valid_until = int(refresh_exp) if refresh_exp else 0
        offline_valid_remaining_seconds = int(offline_expires_in)
        session_valid_remaining_seconds = int(max(0, refresh_exp - now) if refresh_exp else 0)

        heartbeat_interval = session.heartbeat.interval_seconds if session.heartbeat else 0
        grace = session.heartbeat.grace_period_seconds if session.heartbeat else 0
        heartbeat_due_at = self._get_heartbeat_due_at(session)
        heartbeat_overdue_seconds = max(0, int(now - heartbeat_due_at)) if heartbeat_due_at else 0
        needs_heartbeat = (
            heartbeat_interval > 0
            and heartbeat_due_at > 0
            and now >= heartbeat_due_at
            and not is_refresh_expired
        )
        heartbeat_in_flight = self.is_heartbeat_in_flight()
        should_auto_heartbeat_now = self.should_trigger_immediate_heartbeat(now=now)
        warnings = self._build_status_warnings(
            is_valid=is_valid,
            is_refresh_expired=is_refresh_expired,
            is_access_expired=is_access_expired,
            access_expires_in=offline_expires_in,
            needs_heartbeat=needs_heartbeat,
            heartbeat_in_flight=heartbeat_in_flight,
            should_auto_heartbeat_now=should_auto_heartbeat_now,
        )

        if should_auto_heartbeat_now:
            self.request_heartbeat(reason="status_overdue")

        return {
            "activated": is_valid,
            "product": session.product or "",
            "tier": session.tier or "",
            "license_id": session.license_id or "",
            "device_name": session.device_name or "",
            "device_id": self._device_id,
            "features": self.get_features() if is_valid else dict(getattr(session, "features", {}) or {}),
            "access_token_expires_at": access_exp,
            "access_token_expires_in_seconds": int(access_expires_in),
            "refresh_token_expires_at": refresh_exp,
            "offline_valid_until": offline_valid_until,
            "offline_valid_remaining_seconds": offline_valid_remaining_seconds,
            "session_valid_until": session_valid_until,
            "session_valid_remaining_seconds": session_valid_remaining_seconds,
            "session_activated_at": session.activated_at,
            "last_heartbeat_at": self._last_heartbeat_time,
            "last_heartbeat_attempt_at": self._last_heartbeat_attempt_time,
            "last_heartbeat_error": self._last_heartbeat_error,
            "consecutive_heartbeat_failures": self._consecutive_heartbeat_failures,
            "is_access_expired": is_access_expired,
            "is_refresh_expired": is_refresh_expired,
            "needs_heartbeat": needs_heartbeat,
            "should_auto_heartbeat_now": should_auto_heartbeat_now,
            "heartbeat_in_flight": heartbeat_in_flight,
            "heartbeat_interval": heartbeat_interval,
            "heartbeat_grace": grace,
            "heartbeat_due_at": heartbeat_due_at,
            "heartbeat_overdue_seconds": heartbeat_overdue_seconds,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    _HEARTBEAT_REQUEST_COOLDOWN_SECONDS = 5.0

    def heartbeat(self, raise_on_error=False):
        """Send a heartbeat to keep the device session alive.

        Safe to call even if not activated — silently returns.
        If the server is unreachable, the local session remains valid
        until tokens actually expire.
        """
        if self._client.session is None:
            return
        now = time.time()
        self._last_heartbeat_attempt_time = now
        try:
            self._client.heartbeat()
            self._record_heartbeat_success()
        except Exception as exc:
            self._record_heartbeat_failure(exc)
            _log.debug("Heartbeat failed (non-fatal, attempt %d): %s",
                        self._consecutive_heartbeat_failures, exc)
            if raise_on_error:
                raise

    def request_heartbeat(self, reason="manual", force=False, refresh_runtime=False):
        """Start a background heartbeat request when one is needed."""
        session = self._client.session
        if session is None:
            return False

        now = time.time()
        with self._heartbeat_lock:
            if self._is_refresh_expired(session, now=now):
                return False
            if self._heartbeat_in_flight:
                return False
            if (
                not force
                and self._last_heartbeat_attempt_time
                and now - self._last_heartbeat_attempt_time < self._HEARTBEAT_REQUEST_COOLDOWN_SECONDS
            ):
                return False

            self._heartbeat_in_flight = True
            self._last_heartbeat_attempt_time = now
            thread = threading.Thread(
                target=self._run_heartbeat_task,
                args=(reason, refresh_runtime, now),
                name="Rig2LicenseHeartbeat",
                daemon=True,
            )
            self._heartbeat_thread = thread

        try:
            thread.start()
            return True
        except Exception:
            with self._heartbeat_lock:
                self._heartbeat_in_flight = False
                self._heartbeat_thread = None
            raise

    def _run_heartbeat_task(self, reason, refresh_runtime, attempted_at):
        result = {
            "ok": False,
            "reason": reason,
            "refresh_runtime": refresh_runtime,
            "attempted_at": attempted_at,
            "completed_at": time.time(),
            "error": "",
        }
        try:
            self._client.heartbeat()
            result["ok"] = True
            result["completed_at"] = time.time()
        except Exception as exc:
            result["error"] = str(exc)
            result["completed_at"] = time.time()
        finally:
            with self._heartbeat_lock:
                self._heartbeat_result_pending = result
                self._heartbeat_in_flight = False
                self._heartbeat_thread = None

    def consume_heartbeat_result(self):
        """Apply any completed background heartbeat result to local state."""
        with self._heartbeat_lock:
            result = self._heartbeat_result_pending
            self._heartbeat_result_pending = None

        if result is None:
            return None

        self._last_heartbeat_attempt_time = float(result.get("attempted_at", time.time()))
        if result.get("ok"):
            self._record_heartbeat_success(
                completed_at=result.get("completed_at", time.time()),
                refresh_runtime=bool(result.get("refresh_runtime")),
            )
        else:
            self._record_heartbeat_failure(result.get("error", ""))

        return result

    def pop_post_heartbeat_actions(self):
        """Return and clear any main-thread follow-up work after a heartbeat."""
        actions = {
            "sync_native": False,
            "refresh_runtime": False,
        }
        with self._heartbeat_lock:
            if self._native_sync_pending:
                actions["sync_native"] = True
                self._native_sync_pending = False
            if self._runtime_refresh_pending:
                actions["refresh_runtime"] = True
                self._runtime_refresh_pending = False
        return actions

    def is_heartbeat_in_flight(self):
        with self._heartbeat_lock:
            return self._heartbeat_in_flight

    def should_trigger_immediate_heartbeat(self, now=None):
        session = self._client.session
        if session is None:
            return False

        now = time.time() if now is None else now
        if self._is_refresh_expired(session, now=now):
            return False
        if self.is_heartbeat_in_flight():
            return False
        due_at = self._get_heartbeat_due_at(session)
        if not due_at or now < due_at:
            return False
        if (
            self._last_heartbeat_attempt_time
            and now - self._last_heartbeat_attempt_time < self._HEARTBEAT_REQUEST_COOLDOWN_SECONDS
        ):
            return False
        return True

    def _get_heartbeat_due_at(self, session):
        heartbeat_interval = session.heartbeat.interval_seconds if session and session.heartbeat else 0
        if heartbeat_interval <= 0:
            return 0
        last_success = self._last_heartbeat_time or session.activated_at
        if last_success <= 0:
            return 0
        return int(last_success + heartbeat_interval)

    @staticmethod
    def _is_refresh_expired(session, now=None):
        if session is None:
            return True
        now = time.time() if now is None else now
        try:
            refresh_exp = get_token_expiry(session.tokens.refresh_token)
        except Exception:
            refresh_exp = session.activated_at + session.tokens.refresh_expires_in
        return refresh_exp > 0 and now >= refresh_exp

    # ------------------------------------------------------------------
    # Download (for on-demand binary delivery)
    # ------------------------------------------------------------------

    def request_download(self, module, platform_tag="", arch="", artifact=""):
        """Request a scoped download URL for a native binary artifact.

        Returns a DownloadInfo or None if not activated.
        """
        if self._client.session is None:
            return None
        return self._client.request_download(
            module=module,
            addon_version=self.get_addon_version(),
            platform=platform_tag,
            arch=arch,
            artifact=artifact,
        )

    def request_native_grant(self, feature_id: str):
        """Request a signed native grant for a managed feature."""
        if self._client.session is None:
            return None
        platform_name, arch_name, artifact_name = self._native_runtime_selector()
        grant = self._client.request_native_grant(
            feature_id=feature_id,
            addon_version=self.get_addon_version(),
            platform=platform_name,
            arch=arch_name,
            artifact=artifact_name,
        )
        try:
            expires_at = int(get_token_expiry(grant.grant_token) or 0)
        except Exception:
            expires_at = 0
        if expires_at > 0:
            save_cached_native_grant(
                self._native_grant_cache_path,
                CachedNativeGrant(
                    feature_id=grant.feature_id,
                    addon_version=grant.addon_version,
                    grant_token=grant.grant_token,
                    expires_at=expires_at,
                ),
            )
        return grant

    def get_cached_native_grant(self, feature_id: str) -> NativeGrantInfo | None:
        grants = load_cached_native_grants(self._native_grant_cache_path)
        grant = grants.get(feature_id)
        if grant is None:
            return None
        if grant.addon_version != self.get_addon_version():
            return None
        if grant.expires_at <= int(time.time()):
            return None
        return NativeGrantInfo(
            feature_id=grant.feature_id,
            addon_version=grant.addon_version,
            grant_token=grant.grant_token,
            token_type="Bearer",
            expires_in=max(0, grant.expires_at - int(time.time())),
            py_manifest={},
            artifact_manifest={},
        )

    def get_cached_trust_bundle_token(self) -> str:
        return load_cached_trust_bundle(self._trust_bundle_path)

    def get_trust_bundle_token(self, *, allow_network: bool = True) -> str:
        if allow_network:
            try:
                return self._client.fetch_trust_bundle().bundle_token
            except Exception:
                pass
        return self.get_cached_trust_bundle_token()

    @staticmethod
    def _native_runtime_selector() -> tuple[str, str, str]:
        from ..native.loader import PlatformTarget

        target = PlatformTarget.current()
        return target.platform_name, target.arch_name, target.artifact_name

    @staticmethod
    def get_addon_version() -> str:
        from ..core.versioning import SEMVER

        return SEMVER

    def download_file(self, download_info, dest_path, progress_callback=None):
        """Download a binary artifact to a local file."""
        return self._client.download_file(
            download_info,
            dest_path,
            progress_callback=progress_callback,
        )


# Module-level singleton.
_manager: LicenseManager | None = None


def get_license_manager():
    """Return the module-level LicenseManager singleton."""
    global _manager
    if _manager is None:
        _manager = LicenseManager()
    return _manager
