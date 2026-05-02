import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from ._errors import OrbisAuthError


SESSION_VERSION = 3


@dataclass
class HeartbeatPolicy:
    interval_seconds: int
    grace_period_seconds: int


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    offline_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    offline_expires_in: int


@dataclass
class Session:
    """Full activation session state, serializable to/from JSON for persistence."""

    tokens: TokenSet
    product: str
    tier: str
    features: dict[str, Any]
    heartbeat: HeartbeatPolicy
    device_id: str
    device_name: str
    license_id: str
    activated_at: float
    server_url: str

    def access_token_expired(self, skew_seconds: int = 60) -> bool:
        """Check if the access token is expired (or within skew_seconds of expiry)."""
        return time.time() + skew_seconds >= self.activated_at + self.tokens.expires_in

    def refresh_token_expired(self, skew_seconds: int = 60) -> bool:
        """Check if the refresh token is expired (or within skew_seconds of expiry)."""
        return time.time() + skew_seconds >= self.activated_at + self.tokens.refresh_expires_in

    def to_dict(self) -> dict[str, Any]:
        """Serialize session to a JSON-safe dict."""
        return {
            "version": SESSION_VERSION,
            "server_url": self.server_url,
            "tokens": {
                "access_token": self.tokens.access_token,
                "refresh_token": self.tokens.refresh_token,
                "offline_token": self.tokens.offline_token,
                "token_type": self.tokens.token_type,
                "expires_in": self.tokens.expires_in,
                "refresh_expires_in": self.tokens.refresh_expires_in,
                "offline_expires_in": self.tokens.offline_expires_in,
            },
            "product": self.product,
            "tier": self.tier,
            "features": self.features,
            "heartbeat": {
                "interval_seconds": self.heartbeat.interval_seconds,
                "grace_period_seconds": self.heartbeat.grace_period_seconds,
            },
            "device_id": self.device_id,
            "device_name": self.device_name,
            "license_id": self.license_id,
            "activated_at": self.activated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Deserialize a session from a dict (previously produced by to_dict)."""
        tokens_raw = data["tokens"]
        heartbeat_raw = data["heartbeat"]

        return cls(
            tokens=TokenSet(
                access_token=tokens_raw["access_token"],
                refresh_token=tokens_raw["refresh_token"],
                offline_token=tokens_raw.get("offline_token", ""),
                token_type=tokens_raw["token_type"],
                expires_in=tokens_raw["expires_in"],
                refresh_expires_in=tokens_raw["refresh_expires_in"],
                offline_expires_in=tokens_raw.get("offline_expires_in", tokens_raw.get("expires_in", 0)),
            ),
            product=data["product"],
            tier=data["tier"],
            features=data["features"],
            heartbeat=HeartbeatPolicy(
                interval_seconds=heartbeat_raw["interval_seconds"],
                grace_period_seconds=heartbeat_raw["grace_period_seconds"],
            ),
            device_id=data["device_id"],
            device_name=data["device_name"],
            license_id=data["license_id"],
            activated_at=data["activated_at"],
            server_url=data["server_url"],
        )


def save_session_to_file(session: Session, path: str) -> None:
    """Atomically write session to a JSON file."""
    data = json.dumps(session.to_dict(), indent=2, ensure_ascii=False)
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dirname or None, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_session_from_file(path: str) -> Session | None:
    """Load a session from a JSON file. Returns None if the file doesn't exist or is corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, PermissionError):
        return None
    except (json.JSONDecodeError, ValueError, OSError) as e:
        raise OrbisAuthError(f"Failed to read session file: {e}") from e

    if not isinstance(data, dict):
        raise OrbisAuthError("Session file is not a valid JSON object")

    version = data.get("version", 1)
    if version == 1:
        data = _migrate_v1_to_v2(data)
        version = 2
    if version == 2:
        data = _migrate_v2_to_v3(data)
    elif version != SESSION_VERSION:
        raise OrbisAuthError(f"Unsupported session version: {version}")

    return Session.from_dict(data)


def remove_session_file(path: str) -> None:
    """Delete a persisted session file if it exists."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1 session to v2 (adds server_url if missing)."""
    data["version"] = 2
    if "server_url" not in data:
        data["server_url"] = ""
    return data


def _migrate_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    data["version"] = 3
    tokens = data.setdefault("tokens", {})
    if "offline_token" not in tokens:
        tokens["offline_token"] = tokens.get("access_token", "")
    if "offline_expires_in" not in tokens:
        tokens["offline_expires_in"] = tokens.get("expires_in", 0)
    return data
