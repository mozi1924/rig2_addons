import logging
import platform
import uuid

from ..orbisauth import OrbisAuthClient, OrbisAuthError, OrbisAuthTokenError
from .config import (
    DEFAULT_SERVER_URL,
    HTTP_TIMEOUT_SECONDS,
    REFRESH_SKEW_SECONDS,
)
from .paths import get_session_path

_log = logging.getLogger(__name__)


def _generate_device_id():
    """Generate a stable device identifier."""
    try:
        node = uuid.getnode()
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"rig2-blender-{node}").hex[:16]
    except Exception:
        return uuid.uuid4().hex[:16]


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
        self._device_id = _generate_device_id()
        self._device_name = _generate_device_name()
        session_path = get_session_path()
        self._client = OrbisAuthClient(
            server_url=DEFAULT_SERVER_URL,
            session_path=session_path,
            auto_refresh=True,
            refresh_skew_seconds=REFRESH_SKEW_SECONDS,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        self._load_existing_session()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

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
        _log.info("License deactivated.")

    # ------------------------------------------------------------------
    # Feature gating
    # ------------------------------------------------------------------

    def is_activated(self):
        """Check if a valid license session exists (offline check)."""
        if self._client.session is None:
            return False
        try:
            self._client.get_features()
            return True
        except (OrbisAuthTokenError, OrbisAuthError):
            return False

    def is_feature_licensed(self, feature_name):
        """Check if a specific feature is licensed.

        Performs local JWT verification — no server call.
        Returns False if the session is invalid or the feature is not in the token.
        """
        if self._client.session is None:
            return False
        try:
            features = self._client.get_features()
        except (OrbisAuthTokenError, OrbisAuthError):
            return False

        if not features:
            return False
        return bool(features.get(feature_name, False))

    def get_features(self):
        """Return the features dict from the current license (offline check)."""
        try:
            if self._client.session is None:
                return {}
            return self._client.get_features()
        except (OrbisAuthTokenError, OrbisAuthError):
            return {}

    # ------------------------------------------------------------------
    # Status & UI helpers
    # ------------------------------------------------------------------

    def get_status(self):
        """Return a dict describing the current license state for UI display."""
        session = self._client.session
        if session is None:
            return {
                "activated": False,
                "product": "",
                "tier": "",
                "license_id": "",
                "device_name": "",
                "features": {},
            }

        is_valid = self.is_activated()
        return {
            "activated": is_valid,
            "product": session.product or "",
            "tier": session.tier or "",
            "license_id": session.license_id or "",
            "device_name": session.device_name or "",
            "features": self.get_features() if is_valid else {},
        }

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self):
        """Send a heartbeat to keep the device session alive.

        Safe to call even if not activated — silently returns.
        If the server is unreachable, the local session remains valid
        until tokens actually expire.
        """
        if self._client.session is None:
            return
        try:
            self._client.heartbeat()
        except Exception as exc:
            _log.debug("Heartbeat failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Download (for on-demand binary delivery)
    # ------------------------------------------------------------------

    def request_download(self, module, platform_tag="", arch=""):
        """Request a scoped download URL for a native binary artifact.

        Returns a DownloadInfo or None if not activated.
        """
        if self._client.session is None:
            return None
        return self._client.request_download(
            module=module,
            platform=platform_tag,
            arch=arch,
        )

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
