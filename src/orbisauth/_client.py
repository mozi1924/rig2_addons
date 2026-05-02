import time
from dataclasses import dataclass
from typing import Any, Callable

from ._errors import OrbisAuthAPIError, OrbisAuthError, OrbisAuthTokenError
from ._http import _api_request, _stream_request
from ._jwt import verify_access_token, get_token_expiry, _parse_jwt_unverified
from ._session import (
    HeartbeatPolicy,
    Session,
    TokenSet,
    load_session_from_file,
    remove_session_file,
    save_session_to_file,
)


@dataclass
class Device:
    device_id: str
    device_name: str | None
    last_seen: int
    created_at: int


@dataclass
class HeartbeatResponse:
    ok: bool
    license_id: str
    device_id: str
    heartbeat_at: int
    heartbeat: HeartbeatPolicy
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_in: int = 0
    refresh_expires_in: int = 0
    product: str = ""
    tier: str = ""
    features: dict[str, Any] | None = None


@dataclass
class DownloadInfo:
    module: str
    artifact_key: str
    download_url: str
    download_token: str
    token_type: str
    expires_in: int
    addon_version: str = ""
    feature_id: str = ""
    artifact_sha256: str = ""
    artifact_size: int = 0
    artifact_manifest_version: int = 0
    signed_artifact_manifest: str = ""


@dataclass
class NativeGrantInfo:
    feature_id: str
    addon_version: str
    grant_token: str
    token_type: str
    expires_in: int
    py_manifest: dict[str, Any]
    artifact_manifest: dict[str, Any]


_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 300
_DEFAULT_HEARTBEAT_GRACE_SECONDS = 3600


def _api_url(server_url: str, endpoint: str) -> str:
    return f"{server_url.rstrip('/')}/api/v1/{endpoint.lstrip('/')}"


def _coerce_features(raw: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return dict(fallback or {})


def _build_heartbeat_policy(
    heartbeat_raw: Any,
    fallback: HeartbeatPolicy | None = None,
) -> HeartbeatPolicy:
    if not isinstance(heartbeat_raw, dict):
        heartbeat_raw = {}
    return HeartbeatPolicy(
        interval_seconds=int(
            heartbeat_raw.get(
                "interval_seconds",
                fallback.interval_seconds if fallback is not None else _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
            ) or 0
        ),
        grace_period_seconds=int(
            heartbeat_raw.get(
                "grace_period_seconds",
                fallback.grace_period_seconds if fallback is not None else _DEFAULT_HEARTBEAT_GRACE_SECONDS,
            ) or 0
        ),
    )


def _build_token_set(data: dict[str, Any], fallback: TokenSet | None = None) -> TokenSet:
    if fallback is None:
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data.get("expires_in", 0) or 0),
            refresh_expires_in=int(data.get("refresh_expires_in", 0) or 0),
        )
    return TokenSet(
        access_token=data.get("access_token", fallback.access_token) or fallback.access_token,
        refresh_token=data.get("refresh_token", fallback.refresh_token) or fallback.refresh_token,
        token_type=data.get("token_type", fallback.token_type) or fallback.token_type,
        expires_in=int(data.get("expires_in", fallback.expires_in) or fallback.expires_in),
        refresh_expires_in=int(
            data.get("refresh_expires_in", fallback.refresh_expires_in) or fallback.refresh_expires_in
        ),
    )


class OrbisAuthClient:
    """Client for the OrbisAuth license activation and verification server.

    Zero external dependencies — uses only Python standard library.

    Usage::

        client = OrbisAuthClient("https://orbisauth.example.com")
        session = client.activate("LICENSE-KEY", "device-001", "My Machine")
        features = client.get_features()  # local JWT verify, no server call
        client.heartbeat()
    """

    def __init__(
        self,
        server_url: str,
        session_path: str | None = None,
        auto_refresh: bool = True,
        refresh_skew_seconds: int = 120,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.session_path = session_path
        self.auto_refresh = auto_refresh
        self.refresh_skew_seconds = refresh_skew_seconds
        self.timeout_seconds = timeout_seconds

        import threading

        self.session: Session | None = None
        self._lock = threading.RLock()


    # ------------------------------------------------------------------
    # Activation / Session Lifecycle
    # ------------------------------------------------------------------

    def activate(
        self,
        license_key: str,
        device_id: str,
        device_name: str = "",
    ) -> Session:
        """Activate a license key on a device.

        Calls POST /api/v1/activate and returns the Session.
        Auto-persists the session if session_path was set in the constructor.

        Raises:
            OrbisAuthAPIError: LICENSE_NOT_FOUND, LICENSE_BANNED, LICENSE_EXPIRED,
                               LICENSE_INACTIVE, DEVICE_LIMIT_REACHED
        """
        body: dict[str, str] = {
            "license_key": license_key.strip(),
            "device_id": device_id.strip(),
        }
        if device_name.strip():
            body["device_name"] = device_name.strip()

        url = _api_url(self.server_url, "activate")
        data = _api_request("POST", url, json_body=body, timeout=self.timeout_seconds)

        tokens = _build_token_set(data)
        heartbeat = _build_heartbeat_policy(data.get("heartbeat"))

        license_id = self._extract_sub(tokens.access_token)

        self.session = Session(
            tokens=tokens,
            product=data["product"],
            tier=data["tier"],
            features=_coerce_features(data.get("features")),
            heartbeat=heartbeat,
            device_id=device_id.strip(),
            device_name=device_name.strip(),
            license_id=license_id,
            activated_at=time.time(),
            server_url=self.server_url,
        )

        self._persist()
        return self.session

    def refresh(self) -> Session:
        """Refresh the token pair using the current session's refresh token.

        Calls POST /api/v1/refresh. Updates the internal session.
        Auto-persists if session_path was set.

        The session must exist (call activate or load_session first).

        Raises:
            OrbisAuthError: if no active session
            OrbisAuthAPIError: TOKEN_INVALID, TOKEN_REVOKED, TOKEN_EXPIRED,
                               LICENSE_BANNED, LICENSE_EXPIRED, etc.
        """
        with self._lock:
            if self.session is None:
                raise OrbisAuthError("Cannot refresh: no active session.")

            body: dict[str, str] = {"refresh_token": self.session.tokens.refresh_token}

            url = _api_url(self.server_url, "refresh")
            data = _api_request("POST", url, json_body=body, timeout=self.timeout_seconds)

            tokens = _build_token_set(data)
            heartbeat = _build_heartbeat_policy(data.get("heartbeat"), fallback=self.session.heartbeat)

            self.session.tokens = tokens
            self.session.heartbeat = heartbeat
            self.session.activated_at = time.time()

            self._persist()
            return self.session


    def heartbeat(self) -> HeartbeatResponse:
        """Send a heartbeat to keep the device session alive.

        If auto_refresh is enabled and the access token is near expiry,
        the token will be refreshed before sending the heartbeat.

        Returns the heartbeat response from the server.

        Raises:
            OrbisAuthError: if no active session
            OrbisAuthAPIError: LICENSE_BANNED, LICENSE_EXPIRED, DEVICE_NOT_ACTIVE, etc.
        """
        self._ensure_authenticated()
        assert self.session is not None

        url = _api_url(self.server_url, "heartbeat")
        data = _api_request(
            "POST",
            url,
            headers={"Authorization": f"Bearer {self.session.tokens.access_token}"},
            timeout=self.timeout_seconds,
        )

        heartbeat = _build_heartbeat_policy(data.get("heartbeat"), fallback=self.session.heartbeat)
        self.session.heartbeat = heartbeat

        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        expires_in = int(data.get("expires_in", 0) or 0)
        refresh_expires_in = int(data.get("refresh_expires_in", 0) or 0)
        if access_token:
            self.session.tokens = _build_token_set(data, fallback=self.session.tokens)
            self.session.product = str(data.get("product", self.session.product) or self.session.product)
            self.session.tier = str(data.get("tier", self.session.tier) or self.session.tier)
            self.session.features = _coerce_features(data.get("features"), fallback=self.session.features)
            self.session.activated_at = time.time()
            self._persist()

        return HeartbeatResponse(
            ok=data.get("ok", False),
            license_id=data.get("license_id", ""),
            device_id=data.get("device_id", ""),
            heartbeat_at=data.get("heartbeat_at", 0),
            heartbeat=heartbeat,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=data.get("token_type", "Bearer"),
            expires_in=expires_in,
            refresh_expires_in=refresh_expires_in,
            product=str(data.get("product", "") or ""),
            tier=str(data.get("tier", "") or ""),
            features=data.get("features") if isinstance(data.get("features"), dict) else None,
        )

    def deactivate(self) -> None:
        """Clear the current session and delete the persisted session file (if any)."""
        if self.session_path:
            remove_session_file(self.session_path)
        self.session = None

    # ------------------------------------------------------------------
    # Token Verification (offline / local)
    # ------------------------------------------------------------------

    def verify_access_token(self, token: str | None = None, *, allow_network: bool = True) -> Any:
        """Verify the access token JWT locally (no server call).

        Uses the cached JWKS public key. Returns AccessClaims on success.

        If no token is given, uses the current session's access token.

        Raises:
            OrbisAuthError: if no session and no token given
            OrbisAuthTokenError: if JWT verification fails
        """
        t = token
        if t is None:
            if self.session is None:
                raise OrbisAuthError("No session and no token provided.")
            t = self.session.tokens.access_token

        return verify_access_token(
            t,
            server_url=self.server_url,
            timeout=self.timeout_seconds,
            allow_network=allow_network,
        )

    def get_features(self, *, allow_network: bool = True) -> dict[str, Any]:
        """Verify the current access token locally and return its feature flags.

        This is the primary offline feature-gating API. It performs local
        RS256 JWT verification without any server call, so it is fast
        and works offline (once the JWKS has been fetched once).

        Returns the features dict from the token (empty dict if no features).
        Raises OrbisAuthTokenError if the token is invalid or expired.
        """
        claims = self.verify_access_token(allow_network=allow_network)
        return claims.features

    def get_features_no_network(self) -> dict[str, Any]:
        """Return locally verified feature flags using cached JWKS only."""
        return self.get_features(allow_network=False)

    # ------------------------------------------------------------------
    # Device Management
    # ------------------------------------------------------------------

    def list_devices(self) -> list[Device]:
        """List all devices registered to the current license.

        Calls GET /api/v1/devices with the access token.

        Raises:
            OrbisAuthError: if no active session
            OrbisAuthAPIError: on authorization failure
        """
        self._ensure_authenticated()
        assert self.session is not None

        url = _api_url(self.server_url, "devices")
        data = _api_request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self.session.tokens.access_token}"},
            timeout=self.timeout_seconds,
        )

        devices = data.get("devices", [])
        return [
            Device(
                device_id=d["device_id"],
                device_name=d.get("device_name"),
                last_seen=int(d.get("last_seen", 0)),
                created_at=int(d.get("created_at", 0)),
            )
            for d in devices
        ]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def request_native_grant(
        self,
        feature_id: str,
        addon_version: str,
    ) -> NativeGrantInfo:
        self._ensure_authenticated()
        assert self.session is not None

        url = _api_url(self.server_url, "native-grant")
        data = _api_request(
            "POST",
            url,
            json_body={
                "feature_id": feature_id,
                "addon_version": addon_version,
            },
            headers={"Authorization": f"Bearer {self.session.tokens.access_token}"},
            timeout=self.timeout_seconds,
        )
        return NativeGrantInfo(
            feature_id=str(data.get("feature_id", feature_id) or feature_id),
            addon_version=str(data.get("addon_version", addon_version) or addon_version),
            grant_token=data["grant_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data.get("expires_in", 0) or 0),
            py_manifest=data.get("py_manifest", {}) if isinstance(data.get("py_manifest"), dict) else {},
            artifact_manifest=(
                data.get("artifact_manifest", {})
                if isinstance(data.get("artifact_manifest"), dict)
                else {}
            ),
        )

    def request_download(
        self,
        module: str,
        addon_version: str,
        platform: str = "",
        arch: str = "",
        artifact: str = "",
    ) -> DownloadInfo:
        """Request a scoped download URL and token for an artifact.

        Calls GET /api/v1/download. At minimum, module must be provided.
        Either platform or artifact should be provided for the server
        to determine the artifact filename.

        Returns a DownloadInfo with the download URL, token, and expiry.

        Raises:
            OrbisAuthError: if no active session
            OrbisAuthAPIError: on invalid request or authorization failure
        """
        self._ensure_authenticated()
        assert self.session is not None

        params: list[str] = []
        params.append(f"module={_urlencode(module)}")
        params.append(f"addon_version={_urlencode(addon_version)}")
        if platform:
            params.append(f"platform={_urlencode(platform)}")
        if arch:
            params.append(f"arch={_urlencode(arch)}")
        if artifact:
            params.append(f"artifact={_urlencode(artifact)}")

        url = _api_url(self.server_url, f"download?{'&'.join(params)}")
        data = _api_request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self.session.tokens.access_token}"},
            timeout=self.timeout_seconds,
        )

        return DownloadInfo(
            module=data["module"],
            artifact_key=data["artifact_key"],
            download_url=data["download_url"],
            download_token=data["download_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=data["expires_in"],
            addon_version=str(data.get("addon_version", addon_version) or addon_version),
            feature_id=str(data.get("feature_id", "") or ""),
            artifact_sha256=str(data.get("artifact_sha256", "") or ""),
            artifact_size=int(data.get("artifact_size", 0) or 0),
            artifact_manifest_version=int(data.get("artifact_manifest_version", 0) or 0),
            signed_artifact_manifest=str(data.get("signed_artifact_manifest", "") or ""),
        )

    def download_file(
        self,
        download_info: DownloadInfo,
        dest_path: str,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> None:
        """Download a binary artifact to a local file.

        Uses the download URL and token from request_download().
        Streams the file in chunks to keep memory usage low.

        The progress callback receives (bytes_done, total_bytes).
        total_bytes may be None if the server doesn't report Content-Length.

        Raises:
            OrbisAuthAPIError: on download authorization failure
            OrbisAuthNetworkError: on connection failure
        """
        response, content_length = _stream_request(
            download_info.download_url,
            headers={"Authorization": f"Bearer {download_info.download_token}"},
            timeout=self.timeout_seconds,
        )

        try:
            with open(dest_path, "wb") as f:
                downloaded = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, content_length)
        finally:
            response.close()

    # ------------------------------------------------------------------
    # Session Persistence
    # ------------------------------------------------------------------

    def save_session(self, path: str | None = None) -> None:
        """Persist the current session to a JSON file.

        Uses session_path from the constructor if no path is given.

        Raises:
            OrbisAuthError: if no session to save
        """
        if self.session is None:
            raise OrbisAuthError("No session to save.")
        p = path or self.session_path
        if not p:
            raise OrbisAuthError("No session path configured.")
        save_session_to_file(self.session, p)

    def load_session(self, path: str | None = None) -> Session | None:
        """Load a session from a JSON file.

        Uses session_path from the constructor if no path is given.
        Sets self.session on success.
        Returns the loaded Session, or None if the file does not exist.

        Raises:
            OrbisAuthError: if the file exists but is corrupt
        """
        p = path or self.session_path
        if not p:
            return None
        loaded = load_session_from_file(p)
        if loaded is not None:
            # If server_url is empty (migrated from v1), use current server_url
            if not loaded.server_url:
                loaded.server_url = self.server_url
            self.session = loaded
        return loaded

    def is_session_valid(self) -> bool:
        """Check if a session exists and the refresh token has not expired."""
        if self.session is None:
            return False
        return not self.session.refresh_token_expired(skew_seconds=self.refresh_skew_seconds)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        """Check session and optionally auto-refresh before API calls."""
        with self._lock:
            if self.session is None:
                raise OrbisAuthError("Not activated. Call activate() or load_session() first.")

            if not self.auto_refresh:
                return

            if self.session.access_token_expired(skew_seconds=self.refresh_skew_seconds):
                if self.session.refresh_token_expired(skew_seconds=self.refresh_skew_seconds):
                    raise OrbisAuthTokenError(
                        "Session expired: refresh token has expired. Re-activation required."
                    )
                self.refresh()


    def _persist(self) -> None:
        """Persist session to disk if session_path is configured."""
        if self.session_path and self.session:
            try:
                save_session_to_file(self.session, self.session_path)
            except OSError:
                pass

    @staticmethod
    def _extract_sub(token: str) -> str:
        """Extract the 'sub' claim from a JWT without verifying the signature."""
        _, payload = _parse_jwt_unverified(token)
        return payload.get("sub", "")


# ------------------------------------------------------------------
# URL encoding for query parameters (stdlib, no deps)
# ------------------------------------------------------------------

def _urlencode(s: str) -> str:
    """Percent-encode a string for URL query parameters."""
    from urllib.parse import quote

    return quote(s, safe="")
