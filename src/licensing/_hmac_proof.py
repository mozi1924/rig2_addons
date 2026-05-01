"""Compute HMAC proofs for native module license verification.

The HMAC proof proves to the C++ native module that the Python layer
has verified the license is valid. The C++ module recomputes the same
HMAC with its embedded secret and only enables functionality on match.
"""

import hashlib
import hmac
import time

from .registry import get_feature_spec


def compute_license_proof(device_id, secret, expires_at=None):
    """Compute an HMAC-SHA256 hex proof for a given device/expiry.

    Args:
        device_id: The device identifier string.
        secret: 32-byte shared secret from the feature registry.
        expires_at: Unix timestamp when the proof expires.
                    Defaults to now + 1 hour.

    Returns:
        (expires_at, hex_digest) tuple.
    """
    if expires_at is None:
        expires_at = int(time.time()) + 3600

    msg = f"{device_id}:{expires_at}"
    h = hmac.new(secret, msg.encode("utf-8"), hashlib.sha256)
    return expires_at, h.hexdigest()


def compute_feature_proof(feature_id, device_id, expires_at=None):
    """Compute a feature-specific license proof from the registered shared secret."""
    return compute_license_proof(device_id, get_feature_spec(feature_id).shared_secret, expires_at)
