import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ._errors import OrbisAuthTokenError
from ._http import _api_request

# SHA-256 DigestInfo DER prefix for RS256 PKCS#1 v1.5 padding
# ASN.1: SEQUENCE { SEQUENCE { OID SHA-256, NULL }, OCTET STRING (32 bytes) }
_SHA256_DIGEST_INFO_PREFIX = bytes([
    0x30, 0x31, 0x30, 0x0D, 0x06, 0x09,
    0x60, 0x86, 0x48, 0x01, 0x65, 0x03,
    0x04, 0x02, 0x01, 0x05, 0x00, 0x04,
    0x20,
])
DEFAULT_TOKEN_AUDIENCE = "orbisauth-client"
DEFAULT_TOKEN_ISSUER = "orbisauth-worker"
JWKS_ENDPOINT_PATH = "/api/v1/jwks.json"

# In-memory JWKS cache: {server_url: {"keys": [...], "fetched_at": float}}
_jwks_cache: dict[str, dict[str, Any]] = {}


@dataclass
class AccessClaims:
    """Parsed and locally verified access token claims."""
    license_id: str
    product: str
    tier: str
    device_id: str
    features: dict[str, Any]
    issued_at: int
    expires_at: int


def _b64url_decode(data: str) -> bytes:
    """Decode base64url (RFC 7515) to bytes."""
    # Add padding
    rem = len(data) % 4
    if rem:
        data += "=" * (4 - rem)
    # Replace URL-safe chars with standard base64 chars
    return base64.urlsafe_b64decode(data)


def _parse_jwt_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a JWT and parse header + payload without verifying signature.

    Returns (header, payload) as dicts.
    Raises OrbisAuthTokenError if the token is malformed.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise OrbisAuthTokenError("Malformed JWT: expected 3 segments")

    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
    except (ValueError, UnicodeDecodeError) as e:
        raise OrbisAuthTokenError(f"Malformed JWT: {e}") from e

    return header, payload


def _rs256_verify(signing_input: bytes, signature: bytes, modulus: int, exponent: int) -> bool:
    """Verify an RS256 (RSA PKCS#1 v1.5 with SHA-256) signature.

    Uses only Python stdlib: hashlib for SHA-256, pow() for modular exponentiation.
    pow(x, e, n) is C-level and fast for RSA key sizes.
    """
    # SHA-256 hash of the signing input
    message_hash = hashlib.sha256(signing_input).digest()

    # Build the expected PKCS#1 v1.5 padded message
    # Format: 00 01 FF...FF 00 <DigestInfo DER>
    key_length_bytes = (modulus.bit_length() + 7) // 8
    digest_info = _SHA256_DIGEST_INFO_PREFIX + message_hash
    padding_len = key_length_bytes - len(digest_info) - 3
    if padding_len < 8:
        raise OrbisAuthTokenError("RSA key too short for PKCS#1 v1.5 signature")
    padded = b"\x00\x01" + (b"\xff" * padding_len) + b"\x00" + digest_info
    expected = int.from_bytes(padded, "big")

    # RSA verify: decrypted = signature^e mod n
    sig_int = int.from_bytes(signature, "big")
    decrypted = pow(sig_int, exponent, modulus)

    return decrypted == expected


def fetch_jwks(server_url: str, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch the JWK set from the server and cache it in memory.

    Returns the full JWKS response dict (with 'keys' list).
    """
    cached = _jwks_cache.get(server_url)
    if cached is not None:
        return cached

    url = f"{server_url.rstrip('/')}{JWKS_ENDPOINT_PATH}"
    response = _api_request("GET", url, timeout=timeout)
    _jwks_cache[server_url] = response
    return response


def clear_jwks_cache(server_url: str | None = None) -> None:
    """Clear cached JWKS data.

    If server_url is None, clears all cached JWKS.
    """
    if server_url is None:
        _jwks_cache.clear()
    else:
        _jwks_cache.pop(server_url, None)


def verify_access_token(
    token: str,
    server_url: str,
    audience: str = DEFAULT_TOKEN_AUDIENCE,
    issuer: str = DEFAULT_TOKEN_ISSUER,
    clock_skew: int = 30,
    timeout: float = 30.0,
) -> AccessClaims:
    """Verify an RS256-signed access JWT locally.

    Fetches the JWKS from the server on first call (cached in memory).
    Verifies the RS256 signature and validates all required claims.

    Returns AccessClaims with parsed license/product/tier/features.
    Raises OrbisAuthTokenError if verification fails for any reason.
    """
    header, payload = _parse_jwt_unverified(token)

    # Validate header
    if header.get("alg") != "RS256":
        raise OrbisAuthTokenError(f"Unsupported algorithm: {header.get('alg')}")

    kid = header.get("kid")

    # Fetch JWKS and find the matching key
    jwks = fetch_jwks(server_url, timeout=timeout)
    keys = jwks.get("keys", [])

    jwk: dict[str, Any] | None = None
    for k in keys:
        if k.get("kid") == kid:
            jwk = k
            break
    if jwk is None and keys:
        # If no kid match and only one key, use it
        if len(keys) == 1 and (kid is None or keys[0].get("kid") == kid):
            jwk = keys[0]
    if jwk is None:
        raise OrbisAuthTokenError(
            f"Key with kid={kid} not found in JWKS ({len(keys)} keys available)"
        )

    if jwk.get("kty") != "RSA":
        raise OrbisAuthTokenError(f"Unsupported key type: {jwk.get('kty')}")

    # Decode RSA public key from JWK
    try:
        modulus = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        exponent = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    except KeyError as e:
        raise OrbisAuthTokenError(f"JWK missing required field: {e}") from e
    except (ValueError, TypeError) as e:
        raise OrbisAuthTokenError(f"Invalid JWK encoding: {e}") from e

    # Reconstruct signing input and verify signature
    parts = token.split(".")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        signature = _b64url_decode(parts[2])
    except (ValueError, TypeError) as e:
        raise OrbisAuthTokenError(f"Invalid signature encoding: {e}") from e

    if not _rs256_verify(signing_input, signature, modulus, exponent):
        raise OrbisAuthTokenError("Invalid JWT signature")

    # Validate claims
    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise OrbisAuthTokenError("Missing or invalid 'exp' claim")
    if exp + clock_skew < now:
        raise OrbisAuthTokenError("Access token is expired")

    if payload.get("typ") != "access":
        raise OrbisAuthTokenError(f"Wrong token type: {payload.get('typ')}")

    aud = payload.get("aud")
    if isinstance(aud, list):
        if audience not in aud:
            raise OrbisAuthTokenError(f"Wrong audience: {aud}")
    elif aud != audience:
        raise OrbisAuthTokenError(f"Wrong audience: {aud}")

    token_issuer = payload.get("iss")
    if token_issuer != issuer:
        raise OrbisAuthTokenError(f"Wrong issuer: {token_issuer}")

    sub = payload.get("sub")
    product = payload.get("product")
    tier = payload.get("tier")
    device_id = payload.get("device_id")
    if not isinstance(sub, str) or not isinstance(product, str) or not isinstance(tier, str) or not isinstance(device_id, str):
        raise OrbisAuthTokenError("Missing required claims (sub, product, tier, device_id)")

    features = payload.get("features", {})
    if not isinstance(features, dict):
        features = {}

    return AccessClaims(
        license_id=sub,
        product=product,
        tier=tier,
        device_id=device_id,
        features=features,
        issued_at=payload.get("iat", 0),
        expires_at=exp,
    )


def get_token_expiry(token: str) -> int:
    """Extract the exp claim from a JWT without verifying the signature.

    Returns the expiration timestamp as a Unix int.
    Raises OrbisAuthTokenError if the token is malformed.
    """
    _, payload = _parse_jwt_unverified(token)
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise OrbisAuthTokenError("Missing or invalid 'exp' claim")
    return int(exp)
