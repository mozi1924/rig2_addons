class OrbisAuthError(Exception):
    """Base exception for all SDK errors."""


class OrbisAuthAPIError(OrbisAuthError):
    """Server returned an error response."""

    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class OrbisAuthNetworkError(OrbisAuthError):
    """HTTP connection failure, timeout, or DNS error."""


class OrbisAuthTokenError(OrbisAuthError):
    """JWT verification failed (invalid signature, expired, wrong audience)."""
