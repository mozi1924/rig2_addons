#!/usr/bin/env python3
"""Build a distributable Rig2 Blender addon zip."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from versioning import load_version_info, semver, version_tuple

PACKAGE_ROOT_NAME = "rig2_addons"
DEFAULT_DIST_DIR = ROOT / "dist"
PACKAGE_INCLUDE = (
    "__init__.py",
    "blender_manifest.toml",
    "assets",
    "src",
    "version.json",
    "LICENSE",
)
PACKAGE_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.blend1",
    ".DS_Store",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package the Rig2 addon into a zip artifact.")
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=DEFAULT_DIST_DIR,
        help="Directory where the zip artifact will be written.",
    )
    parser.add_argument(
        "--native-dir",
        type=Path,
        default=None,
        help="Optional extracted native runtime directory to bundle into src/native/binaries.",
    )
    parser.add_argument(
        "--package-name",
        default=PACKAGE_ROOT_NAME,
        help="Package id/root directory name. Used for legacy zip layout and default output name.",
    )
    parser.add_argument(
        "--format",
        choices=("extension", "legacy"),
        default="extension",
        help="Build Blender 4.2+ extension zip (default) or legacy addon zip layout.",
    )
    parser.add_argument(
        "--compresslevel",
        type=int,
        default=9,
        choices=range(0, 10),
        metavar="0-9",
        help="ZIP deflate compression level. Defaults to 9 for smallest compatible archives.",
    )
    return parser.parse_args()


def copy_package_tree(staging_root: Path, package_name: str) -> Path:
    package_root = staging_root / package_name
    package_root.mkdir(parents=True, exist_ok=True)

    for item_name in PACKAGE_INCLUDE:
        source = ROOT / item_name
        destination = package_root / item_name
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(*PACKAGE_IGNORE_PATTERNS),
            )
        else:
            shutil.copy2(source, destination)
    shutil.rmtree(package_root / "src" / "native" / "binaries", ignore_errors=True)
    return package_root


def copy_extension_tree(staging_root: Path) -> Path:
    for item_name in PACKAGE_INCLUDE:
        source = ROOT / item_name
        destination = staging_root / item_name
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(*PACKAGE_IGNORE_PATTERNS),
            )
        else:
            shutil.copy2(source, destination)
    shutil.rmtree(staging_root / "src" / "native" / "binaries", ignore_errors=True)
    return staging_root


def overlay_native_binaries(package_root: Path, native_dir: Path) -> None:
    destination = package_root / "src" / "native" / "binaries"
    destination.mkdir(parents=True, exist_ok=True)
    for source in native_dir.rglob("*"):
        if not source.is_file():
            continue
        rel_path = source.relative_to(native_dir)
        target = destination / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def inject_bl_info_version(init_file: Path, version_literal: tuple[int, int, int]) -> None:
    content = init_file.read_text(encoding="utf-8")
    content, count = re.subn(
        r'"version":\s*(BL_INFO_VERSION|\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)),',
        f'"version": {version_literal},',
        content,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Could not inject bl_info version into {init_file}")
    init_file.write_text(content, encoding="utf-8")


def inject_manifest_version(manifest_file: Path, version_string: str) -> None:
    content = manifest_file.read_text(encoding="utf-8")
    content, count = re.subn(
        r'^version\s*=\s*".*?"\s*$',
        f'version = "{version_string}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"Could not inject manifest version into {manifest_file}")
    manifest_file.write_text(content, encoding="utf-8")


def build_zip(
    source_root: Path,
    dist_dir: Path,
    artifact_name: str,
    version_string: str,
    compresslevel: int,
    include_source_dir: bool = False,
) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    archive_path = dist_dir / f"{artifact_name}-{version_string}.zip"
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=compresslevel,
    ) as zf:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file():
                continue
            archive_name = source.relative_to(source_root.parent) if include_source_dir else source.relative_to(source_root)
            zf.write(source, archive_name)
    return archive_path


def main() -> int:
    args = parse_args()
    version = load_version_info()
    version_string = semver(version)
    blender_version = version_tuple(version)

    native_dir = args.native_dir.resolve() if args.native_dir else None
    if native_dir is not None and not native_dir.exists():
        raise FileNotFoundError(f"Native directory does not exist: {native_dir}")

    with tempfile.TemporaryDirectory(prefix="rig2-addon-package-") as temp_dir:
        staging_root = Path(temp_dir)
        if args.format == "legacy":
            package_root = copy_package_tree(staging_root, args.package_name)
        else:
            package_root = copy_extension_tree(staging_root)
        if native_dir is not None:
            overlay_native_binaries(package_root, native_dir)
        inject_bl_info_version(package_root / "__init__.py", blender_version)
        inject_manifest_version(package_root / "blender_manifest.toml", version_string)
        artifact_name = args.package_name if args.format == "legacy" else "rig2_extension"
        archive_path = build_zip(
            package_root,
            args.dist_dir.resolve(),
            artifact_name,
            version_string,
            args.compresslevel,
            include_source_dir=args.format == "legacy",
        )

    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
