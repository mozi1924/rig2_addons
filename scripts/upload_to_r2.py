#!/usr/bin/env python3
"""Upload Rig2 native binaries to Cloudflare R2 for Orbisauth download delivery.

Target R2 structure (per R2_STORAGE_STRUCTURE.md):
    {storage_prefix}/{module}/{platform}/{arch}/{artifact}

Where artifact is the platform-inferred filename:
    mac → mac.dylib   linux → linux.so   win → win.dll

Requires boto3 (install with: pip install boto3).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Platform tag directory name → (platform, arch, artifact_name)
_PLATFORM_TAG_MAP: dict[str, tuple[str, str, str]] = {
    "darwin-x86_64-abi3": ("mac", "amd64", "mac.dylib"),
    "darwin-arm64-abi3": ("mac", "arm64", "mac.dylib"),
    "linux-x86_64-abi3": ("linux", "amd64", "linux.so"),
    "linux-arm64-abi3": ("linux", "arm64", "linux.so"),
    "win32-x86_64-abi3": ("win", "amd64", "win.dll"),
    "win32-arm64-abi3": ("win", "arm64", "win.dll"),
}

_MODULE_NAMES = ("rig2_face_cap", "rig2_miframes", "rig2_r2bb")


def _find_binary(platform_dir: Path, module_name: str) -> Path | None:
    """Return the first file in *platform_dir* whose name starts with *module_name*."""
    for candidate in platform_dir.iterdir():
        if candidate.is_file() and candidate.name.startswith(module_name):
            return candidate
    return None


def _upload_file(s3_client, local_path: Path, bucket: str, key: str) -> None:
    s3_client.upload_file(str(local_path), bucket, key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary-dir",
        type=Path,
        required=True,
        help="Directory containing platform-tagged native binary folders",
    )
    parser.add_argument(
        "--storage-prefix",
        required=True,
        help="R2 storage prefix (product ID, e.g. 'rig2')",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("R2_BUCKET_NAME", ""),
        help="R2 bucket name",
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("R2_ENDPOINT_URL", ""),
        help="Cloudflare R2 S3 endpoint URL",
    )
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("R2_ACCESS_KEY_ID", ""),
        help="R2 access key ID",
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        help="R2 secret access key",
    )
    args = parser.parse_args()

    if not args.bucket:
        parser.error("--bucket is required (or set R2_BUCKET_NAME env var)")
    if not args.endpoint_url:
        parser.error("--endpoint-url is required (or set R2_ENDPOINT_URL env var)")
    if not args.access_key_id or not args.secret_access_key:
        parser.error(
            "R2 credentials are required "
            "(set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY env vars)"
        )

    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=args.endpoint_url,
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key,
    )

    binary_dir = args.binary_dir
    if not binary_dir.is_dir():
        raise FileNotFoundError(f"Binary directory not found: {binary_dir}")

    uploaded = 0

    for tag, (platform, arch, artifact_name) in _PLATFORM_TAG_MAP.items():
        platform_dir = binary_dir / tag
        if not platform_dir.is_dir():
            print(f"[r2-upload] skip {tag}: directory not found")
            continue

        for module_name in _MODULE_NAMES:
            binary_path = _find_binary(platform_dir, module_name)
            if binary_path is None:
                print(f"[r2-upload] skip {tag}/{module_name}: binary not found")
                continue

            key = f"{args.storage_prefix}/{module_name}/{platform}/{arch}/{artifact_name}"
            print(f"[r2-upload] {binary_path.name} -> s3://{args.bucket}/{key}")
            _upload_file(s3, binary_path, args.bucket, key)
            uploaded += 1

    if uploaded == 0:
        raise RuntimeError("No binaries were uploaded — check binary-dir contents")

    print(f"[r2-upload] successfully uploaded {uploaded} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
