import base64
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any

from ._errors import OrbisAuthTokenError
from ._http import _api_request

try:
    from ._trusted_keys import DEFAULT_TRUSTED_JWKS
except Exception:
    DEFAULT_TRUSTED_JWKS = {"keys": []}

# SHA-256 DigestInfo DER prefix for RS256 PKCS#1 v1.5 padding
_SHA256_DIGEST_INFO_PREFIX = bytes([
    0x30, 0x31, 0x30, 0x0D, 0x06, 0x09,
    0x60, 0x86, 0x48, 0x01, 0x65, 0x03,
    0x04, 0x02, 0x01, 0x05, 0x00, 0x04,
    0x20,
])
DEFAULT_TOKEN_AUDIENCE = "orbisauth-client"
DEFAULT_OFFLINE_AUDIENCE = "orbisauth-offline-session"
DEFAULT_TRUST_BUNDLE_AUDIENCE = "orbisauth-trust-bundle"
DEFAULT_TOKEN_ISSUER = "orbisauth-worker"
JWKS_ENDPOINT_PATH = "/api/v1/jwks.json"
TRUST_BUNDLE_ENDPOINT_PATH = "/api/v1/trust-bundle"

_jwks_cache: dict[str, dict[str, Any]] = {}
_trust_bundle_cache: dict[str, dict[str, Any]] = {}
_trust_bundle_cache_path: str | None = None


def set_trust_bundle_cache_path(path: str | None) -> None:
    global _trust_bundle_cache_path
    _trust_bundle_cache_path = path


def get_cached_jwks(server_url: str) -> dict[str, Any] | None:
    return _jwks_cache.get(server_url)


@dataclass
class AccessClaims:
    license_id: str
    product: str
    tier: str
    device_id: str
    features: dict[str, Any]
    issued_at: int
    expires_at: int


def _b64url_decode(data: str) -> bytes:
    rem = len(data) % 4
    if rem:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data)


def _parse_jwt_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
    message_hash = hashlib.sha256(signing_input).digest()
    key_length_bytes = (modulus.bit_length() + 7) // 8
    digest_info = _SHA256_DIGEST_INFO_PREFIX + message_hash
    padding_len = key_length_bytes - len(digest_info) - 3
    if padding_len < 8:
        raise OrbisAuthTokenError("RSA key too short for PKCS#1 v1.5 signature")
    padded = b"\x00\x01" + (b"\xff" * padding_len) + b"\x00" + digest_info
    expected = int.from_bytes(padded, "big")
    sig_int = int.from_bytes(signature, "big")
    decrypted = pow(sig_int, exponent, modulus)
    return decrypted == expected


def _normalize_keys(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = payload.get("keys", [])
    if not isinstance(keys, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in keys:
        if not isinstance(item, dict):
            continue
        if item.get("kty") != "RSA":
            continue
        if not isinstance(item.get("n"), str) or not isinstance(item.get("e"), str):
            continue
        normalized.append(item)
    return normalized


def _claims_from_payload(payload: dict[str, Any], *, clock_skew: int) -> AccessClaims:
    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise OrbisAuthTokenError("Missing or invalid 'exp' claim")
    if exp + clock_skew < now:
        raise OrbisAuthTokenError("Token is expired")

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


def _verify_with_keys(
    token: str,
    keys: list[dict[str, Any]],
    *,
    audience: str,
    issuer: str,
    expected_type: str,
    clock_skew: int,
) -> AccessClaims:
    header, payload = _parse_jwt_unverified(token)
    if header.get("alg") != "RS256":
        raise OrbisAuthTokenError(f"Unsupported algorithm: {header.get('alg')}")

    kid = header.get("kid")
    jwk: dict[str, Any] | None = None
    for k in keys:
        if k.get("kid") == kid:
            jwk = k
            break
    if jwk is None and keys:
        if len(keys) == 1 and (kid is None or keys[0].get("kid") == kid):
            jwk = keys[0]
    if jwk is None:
        raise OrbisAuthTokenError(
            f"Key with kid={kid} not found in key set ({len(keys)} keys available)"
        )

    try:
        modulus = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        exponent = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    except KeyError as e:
        raise OrbisAuthTokenError(f"JWK missing required field: {e}") from e
    except (ValueError, TypeError) as e:
        raise OrbisAuthTokenError(f"Invalid JWK encoding: {e}") from e

    parts = token.split(".")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        signature = _b64url_decode(parts[2])
    except (ValueError, TypeError) as e:
        raise OrbisAuthTokenError(f"Invalid signature encoding: {e}") from e

    if not _rs256_verify(signing_input, signature, modulus, exponent):
        raise OrbisAuthTokenError("Invalid JWT signature")

    if payload.get("typ") != expected_type:
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

    return _claims_from_payload(payload, clock_skew=clock_skew)


def _write_bundle_cache(path: str, bundle_token: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory or None, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"bundle_token": bundle_token}, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_bundle_cache(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("bundle_token", "") or "").strip()


def clear_jwks_cache(server_url: str | None = None) -> None:
    if server_url is None:
        _jwks_cache.clear()
        _trust_bundle_cache.clear()
    else:
        _jwks_cache.pop(server_url, None)
        _trust_bundle_cache.pop(server_url, None)


def verify_trust_bundle_token(
    bundle_token: str,
    *,
    clock_skew: int = 30,
) -> dict[str, Any]:
    keys = _normalize_keys(DEFAULT_TRUSTED_JWKS)
    if not keys:
        raise OrbisAuthTokenError("No trusted default keys are bundled with the addon")

    header, payload = _parse_jwt_unverified(bundle_token)
    if header.get("alg") != "RS256":
        raise OrbisAuthTokenError(f"Unsupported algorithm: {header.get('alg')}")

    kid = header.get("kid")
    jwk: dict[str, Any] | None = None
    for key in keys:
        if key.get("kid") == kid:
            jwk = key
            break
    if jwk is None and len(keys) == 1:
        jwk = keys[0]
    if jwk is None:
        raise OrbisAuthTokenError(f"Trusted key with kid={kid} not found")

    modulus = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    exponent = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    parts = bundle_token.split(".")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _b64url_decode(parts[2])
    if not _rs256_verify(signing_input, signature, modulus, exponent):
        raise OrbisAuthTokenError("Invalid trust bundle signature")

    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp + clock_skew < now:
        raise OrbisAuthTokenError("Trust bundle is expired")
    if payload.get("typ") != "trust_bundle":
        raise OrbisAuthTokenError(f"Wrong trust bundle type: {payload.get('typ')}")
    aud = payload.get("aud")
    if isinstance(aud, list):
        if DEFAULT_TRUST_BUNDLE_AUDIENCE not in aud:
            raise OrbisAuthTokenError(f"Wrong trust bundle audience: {aud}")
    elif aud != DEFAULT_TRUST_BUNDLE_AUDIENCE:
        raise OrbisAuthTokenError(f"Wrong trust bundle audience: {aud}")
    if payload.get("iss") != DEFAULT_TOKEN_ISSUER:
        raise OrbisAuthTokenError(f"Wrong trust bundle issuer: {payload.get('iss')}")
    payload_keys = _normalize_keys(payload)
    if not payload_keys:
        raise OrbisAuthTokenError("Trust bundle has no usable keys")
    return {
        "keys": payload_keys,
        "fetched_at": float(time.time()),
        "token": bundle_token,
    }


def fetch_trust_bundle(server_url: str, timeout: float = 30.0, allow_network: bool = True) -> dict[str, Any]:
    cached = _trust_bundle_cache.get(server_url)
    if cached is not None:
        return cached

    if _trust_bundle_cache_path:
        token = _load_bundle_cache(_trust_bundle_cache_path)
        if token:
            try:
                cached = verify_trust_bundle_token(token)
                _trust_bundle_cache[server_url] = cached
                _jwks_cache[server_url] = {"keys": cached["keys"], "fetched_at": cached["fetched_at"]}
                return cached
            except OrbisAuthTokenError:
                pass

    if not allow_network:
        raise OrbisAuthTokenError("Trust bundle cache is empty")

    url = f"{server_url.rstrip('/')}{TRUST_BUNDLE_ENDPOINT_PATH}"
    response = _api_request("GET", url, timeout=timeout)
    bundle_token = str(response.get("bundle_token", "") or "").strip()
    if not bundle_token:
        raise OrbisAuthTokenError("Trust bundle response is missing bundle_token")
    verified = verify_trust_bundle_token(bundle_token)
    _trust_bundle_cache[server_url] = verified
    _jwks_cache[server_url] = {"keys": verified["keys"], "fetched_at": verified["fetched_at"]}
    if _trust_bundle_cache_path:
        try:
            _write_bundle_cache(_trust_bundle_cache_path, bundle_token)
        except OSError:
            pass
    return verified


def _resolve_verification_keys(server_url: str, timeout: float, allow_network: bool) -> list[dict[str, Any]]:
    cached = _jwks_cache.get(server_url)
    if cached is not None:
        keys = _normalize_keys(cached)
        if keys:
            return keys

    try:
        bundle = fetch_trust_bundle(server_url, timeout=timeout, allow_network=allow_network)
        keys = _normalize_keys(bundle)
        if keys:
            return keys
    except OrbisAuthTokenError:
        if not allow_network:
            default_keys = _normalize_keys(DEFAULT_TRUSTED_JWKS)
            if default_keys:
                return default_keys
            raise

    if allow_network:
        url = f"{server_url.rstrip('/')}{JWKS_ENDPOINT_PATH}"
        response = _api_request("GET", url, timeout=timeout)
        _jwks_cache[server_url] = response
        keys = _normalize_keys(response)
        if keys:
            return keys

    default_keys = _normalize_keys(DEFAULT_TRUSTED_JWKS)
    if default_keys:
        return default_keys
    raise OrbisAuthTokenError("No trusted keys available")


def fetch_jwks(server_url: str, timeout: float = 30.0, allow_network: bool = True) -> dict[str, Any]:
    keys = _resolve_verification_keys(server_url, timeout=timeout, allow_network=allow_network)
    return {"keys": keys}


def verify_access_token(
    token: str,
    server_url: str,
    audience: str = DEFAULT_TOKEN_AUDIENCE,
    issuer: str = DEFAULT_TOKEN_ISSUER,
    clock_skew: int = 30,
    timeout: float = 30.0,
    allow_network: bool = True,
) -> AccessClaims:
    keys = _resolve_verification_keys(server_url, timeout=timeout, allow_network=allow_network)
    return _verify_with_keys(
        token,
        keys,
        audience=audience,
        issuer=issuer,
        expected_type="access",
        clock_skew=clock_skew,
    )


def verify_offline_token(
    token: str,
    server_url: str,
    audience: str = DEFAULT_OFFLINE_AUDIENCE,
    issuer: str = DEFAULT_TOKEN_ISSUER,
    clock_skew: int = 30,
    timeout: float = 30.0,
    allow_network: bool = True,
) -> AccessClaims:
    keys = _resolve_verification_keys(server_url, timeout=timeout, allow_network=allow_network)
    return _verify_with_keys(
        token,
        keys,
        audience=audience,
        issuer=issuer,
        expected_type="offline",
        clock_skew=clock_skew,
    )


def get_token_expiry(token: str) -> int:
    _header, payload = _parse_jwt_unverified(token)
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise OrbisAuthTokenError("Missing or invalid 'exp' claim")
    return exp
