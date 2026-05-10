#!/usr/bin/env python3
"""Validate vendored OrbisAuth SDK contract used by Rig2 licensing."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SDK_PACKAGE_ROOT = ROOT / "src"


def _load_sdk_module():
    if str(SDK_PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(SDK_PACKAGE_ROOT))
    return importlib.import_module("orbisauth._client")


def validate_orbisauth_sdk_contract() -> list[str]:
    errors: list[str] = []
    sdk = _load_sdk_module()

    client_cls = getattr(sdk, "OrbisAuthClient", None)
    if client_cls is None:
        return ["OrbisAuthClient is missing from vendored SDK"]

    required_client_methods = {
        "activate",
        "heartbeat",
        "load_session",
        "deactivate",
        "get_features",
        "request_download",
        "request_native_grant",
        "fetch_trust_bundle",
        "get_latest_addon_version",
        "download_file",
    }
    for name in sorted(required_client_methods):
        value = getattr(client_cls, name, None)
        if not callable(value):
            errors.append(f"OrbisAuthClient missing required callable: {name}")

    download_info_cls = getattr(sdk, "DownloadInfo", None)
    if download_info_cls is None:
        errors.append("DownloadInfo dataclass is missing")
    else:
        fields = set(getattr(download_info_cls, "__annotations__", {}).keys())
        required_fields = {
            "module",
            "artifact_key",
            "download_url",
            "download_token",
            "token_type",
            "expires_in",
            "addon_version",
            "feature_id",
            "artifact_sha256",
            "artifact_size",
            "artifact_manifest_version",
            "signed_artifact_manifest",
        }
        missing = sorted(required_fields - fields)
        if missing:
            errors.append(f"DownloadInfo missing fields: {missing!r}")

    native_grant_info_cls = getattr(sdk, "NativeGrantInfo", None)
    if native_grant_info_cls is None:
        errors.append("NativeGrantInfo dataclass is missing")
    else:
        fields = set(getattr(native_grant_info_cls, "__annotations__", {}).keys())
        required_fields = {
            "feature_id",
            "addon_version",
            "grant_token",
            "token_type",
            "expires_in",
            "py_manifest",
            "artifact_manifest",
        }
        missing = sorted(required_fields - fields)
        if missing:
            errors.append(f"NativeGrantInfo missing fields: {missing!r}")

    latest_version_info_cls = getattr(sdk, "LatestAddonVersionInfo", None)
    if latest_version_info_cls is None:
        errors.append("LatestAddonVersionInfo dataclass is missing")
    else:
        fields = set(getattr(latest_version_info_cls, "__annotations__", {}).keys())
        required_fields = {
            "product_id",
            "storage_prefix",
            "addon_version",
            "updated_at",
            "source",
        }
        missing = sorted(required_fields - fields)
        if missing:
            errors.append(f"LatestAddonVersionInfo missing fields: {missing!r}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    errors = validate_orbisauth_sdk_contract()
    if errors:
        raise SystemExit("Invalid vendored OrbisAuth SDK contract:\n" + "\n".join(errors))

    print("[validate-orbisauth-sdk] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
