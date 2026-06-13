#!/usr/bin/env python3
"""Upload the built addon zip and Blender extension repository index to Cloudflare R2.

Uploads:
  1. ``<storage-prefix>/<addon-version>/rig2_extension-<version>.zip``  — versioned addon
  2. ``<storage-prefix>/latest.zip``                                    — always latest
  3. ``<storage-prefix>/index.json``                                    — Blender repo index
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from pathlib import Path

import boto3
from botocore.config import Config

_log = logging.getLogger(__name__)


def _resolve_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {key}")
    return value


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _create_s3_client():
    endpoint_url = _resolve_env("R2_ENDPOINT_URL")
    access_key = _resolve_env("R2_ACCESS_KEY_ID")
    secret_key = _resolve_env("R2_SECRET_ACCESS_KEY")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            region_name="auto",
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _upload_file(s3, bucket: str, key: str, local_path: Path, content_type: str) -> str:
    size = local_path.stat().st_size
    sha256 = _sha256_file(local_path)
    _log.info("Uploading %s → s3://%s/%s  (%d bytes, sha256=%s)", local_path.name, bucket, key, size, sha256)
    s3.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={
            "ContentType": content_type,
            "Metadata": {
                "sha256": sha256,
                "size": str(size),
            },
        },
    )
    return sha256


def upload(args: argparse.Namespace) -> None:
    bucket = _resolve_env("R2_PUBLIC_BUCKET_NAME")
    s3 = _create_s3_client()
    addon_version = args.addon_version
    storage_prefix = args.storage_prefix.rstrip("/")

    artifact_path = Path(args.artifact)
    index_path = Path(args.index_file) if args.index_file else None
    if not artifact_path.exists():
        raise SystemExit(f"Addon artifact not found: {artifact_path}")

    # 1. Versioned addon zip
    versioned_key = f"{storage_prefix}/{addon_version}/{artifact_path.name}"
    _upload_file(s3, bucket, versioned_key, artifact_path, "application/zip")
    _log.info("✓ Versioned addon: s3://%s/%s", bucket, versioned_key)

    # 2. Latest.zip (always-point-to-latest)
    latest_key = args.latest_key or f"{storage_prefix}/latest.zip"
    _upload_file(s3, bucket, latest_key, artifact_path, "application/zip")
    _log.info("✓ Latest addon: s3://%s/%s", bucket, latest_key)

    # 3. Repository index
    if index_path and index_path.exists():
        index_key = args.index_key or f"{storage_prefix}/index.json"
        _upload_file(s3, bucket, index_key, index_path, "application/json")
        _log.info("✓ Repository index: s3://%s/%s", bucket, index_key)

    _log.info("Upload complete for version %s.", addon_version)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload addon artifacts to Cloudflare R2.")
    parser.add_argument("--artifact", required=True, help="Path to the addon .zip file.")
    parser.add_argument("--addon-version", required=True, help="Semantic version string (e.g. 1.1.7).")
    parser.add_argument("--storage-prefix", default="rig2", help="R2 key prefix (default: rig2).")
    parser.add_argument("--latest-key", default=None, help="R2 key for latest.zip (default: <prefix>/latest.zip).")
    parser.add_argument("--index-file", default=None, help="Path to the Blender extension index.json.")
    parser.add_argument("--index-key", default=None, help="R2 key for index.json (default: <prefix>/index.json).")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[r2-upload] %(message)s")
    args = parse_args()
    upload(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
