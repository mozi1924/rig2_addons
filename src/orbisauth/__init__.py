"""OrbisAuth Python SDK — Zero-dependency license activation and verification client.

Designed for Blender plugins and other embedded Python environments.
Uses only Python standard library modules.
"""

from ._client import (
    Device,
    DownloadInfo,
    HeartbeatResponse,
    NativeGrantInfo,
    OrbisAuthClient,
)
from ._errors import (
    OrbisAuthAPIError,
    OrbisAuthError,
    OrbisAuthNetworkError,
    OrbisAuthTokenError,
)
from ._jwt import (
    AccessClaims,
    clear_jwks_cache,
    fetch_jwks,
    verify_access_token,
)
from ._session import (
    HeartbeatPolicy,
    Session,
    TokenSet,
    load_session_from_file,
    save_session_to_file,
)

__all__ = [
    # Main client
    "OrbisAuthClient",
    # Data classes
    "Session",
    "TokenSet",
    "HeartbeatPolicy",
    "AccessClaims",
    "Device",
    "HeartbeatResponse",
    "DownloadInfo",
    "NativeGrantInfo",
    # JWT utilities
    "verify_access_token",
    "fetch_jwks",
    "clear_jwks_cache",
    # Session persistence
    "save_session_to_file",
    "load_session_from_file",
    # Errors
    "OrbisAuthError",
    "OrbisAuthAPIError",
    "OrbisAuthNetworkError",
    "OrbisAuthTokenError",
]
