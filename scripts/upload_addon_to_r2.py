#!/usr/bin/env python3
"""Upload packaged Rig2 addon zips to Cloudflare R2."""

from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path


def _upload_file(s3_client, local_path: Path, bucket: str, key: str) -> None:
    extra_args = {}
    content_type, _ = mimetypes.guess_type(local_path.name)
    if content_type:
        extra_args["ContentType"] = content_type

    if extra_args:
        s3_client.upload_file(str(local_path), bucket, key, ExtraArgs=extra_args)
    else:
        s3_client.upload_file(str(local_path), bucket, key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Packaged addon zip file to upload.",
    )
    parser.add_argument(
        "--storage-prefix",
        default="rig2",
        help="R2 storage prefix, for example 'rig2'.",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("R2_PUBLIC_BUCKET_NAME", "public-assets"),
        help="R2 bucket name.",
    )
    parser.add_argument(
        "--latest-key",
        default="",
        help="Optional additional object key for a stable latest alias, for example 'rig2/latest.zip'.",
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("R2_ENDPOINT_URL", ""),
        help="Cloudflare R2 S3 endpoint URL.",
    )
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("R2_ACCESS_KEY_ID", ""),
        help="R2 access key ID.",
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        help="R2 secret access key.",
    )
    args = parser.parse_args()

    artifact = args.artifact
    if not artifact.is_file():
        raise FileNotFoundError(f"Addon artifact not found: {artifact}")
    if not args.bucket:
        parser.error("--bucket is required")
    if not args.endpoint_url:
        parser.error("--endpoint-url is required (or set R2_ENDPOINT_URL env var)")
    if not args.access_key_id or not args.secret_access_key:
        parser.error(
            "R2 credentials are required "
            "(set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY env vars)"
        )

    key = f"{args.storage_prefix.rstrip('/')}/{artifact.name}"

    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=args.endpoint_url,
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key,
    )

    print(f"[r2-addon-upload] {artifact.name} -> s3://{args.bucket}/{key}")
    _upload_file(s3, artifact, args.bucket, key)
    if args.latest_key:
        latest_key = args.latest_key.lstrip("/")
        print(f"[r2-addon-upload] {artifact.name} -> s3://{args.bucket}/{latest_key}")
        _upload_file(s3, artifact, args.bucket, latest_key)
    print("[r2-addon-upload] upload complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
