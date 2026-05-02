from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from ..orbisauth._jwt import get_token_expiry


@dataclass
class CachedNativeGrant:
    feature_id: str
    addon_version: str
    grant_token: str
    expires_at: int


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory or None, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_cached_trust_bundle(path: str) -> str:
    data = _read_json(path)
    token = str(data.get("bundle_token", "") or "").strip()
    if not token:
        return ""
    try:
        if get_token_expiry(token) <= 0:
            return ""
    except Exception:
        return ""
    return token


def save_cached_trust_bundle(path: str, bundle_token: str) -> None:
    token = str(bundle_token or "").strip()
    if not token:
        clear_cached_trust_bundle(path)
        return
    expires_at = 0
    try:
        expires_at = int(get_token_expiry(token) or 0)
    except Exception:
        expires_at = 0
    _write_json(
        path,
        {
            "bundle_token": token,
            "expires_at": expires_at,
        },
    )


def clear_cached_trust_bundle(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def load_cached_native_grants(path: str) -> dict[str, CachedNativeGrant]:
    data = _read_json(path)
    grants_raw = data.get("grants", {})
    if not isinstance(grants_raw, dict):
        return {}
    grants: dict[str, CachedNativeGrant] = {}
    for feature_id, raw in grants_raw.items():
        if not isinstance(raw, dict):
            continue
        token = str(raw.get("grant_token", "") or "").strip()
        addon_version = str(raw.get("addon_version", "") or "").strip()
        expires_at = int(raw.get("expires_at", 0) or 0)
        if not token or not addon_version or expires_at <= 0:
            continue
        grants[str(feature_id)] = CachedNativeGrant(
            feature_id=str(feature_id),
            addon_version=addon_version,
            grant_token=token,
            expires_at=expires_at,
        )
    return grants


def save_cached_native_grant(path: str, grant: CachedNativeGrant) -> None:
    grants = load_cached_native_grants(path)
    grants[grant.feature_id] = grant
    _write_json(
        path,
        {
            "grants": {
                feature_id: {
                    "addon_version": item.addon_version,
                    "grant_token": item.grant_token,
                    "expires_at": item.expires_at,
                }
                for feature_id, item in sorted(grants.items())
            }
        },
    )


def clear_cached_native_grants(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
