#!/usr/bin/env python3
"""Build a distributable Rig2 Blender addon zip."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from versioning import load_version_info, semver, version_tuple

PACKAGE_ROOT_NAME = "rig2_addons"
DEFAULT_DIST_DIR = ROOT / "dist"
PACKAGE_INCLUDE = (
    "__init__.py",
    "assets",
    "src",
    "version.json",
    "LICENSE",
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
        help="Root directory name inside the zip archive.",
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
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
        else:
            shutil.copy2(source, destination)
    shutil.rmtree(package_root / "src" / "native" / "binaries", ignore_errors=True)
    return package_root


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


def build_zip(package_root: Path, dist_dir: Path, package_name: str, version_string: str) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    archive_base = dist_dir / f"{package_name}-{version_string}"
    archive_path = shutil.make_archive(str(archive_base), "zip", package_root.parent, package_root.name)
    return Path(archive_path)


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
        package_root = copy_package_tree(staging_root, args.package_name)
        if native_dir is not None:
            overlay_native_binaries(package_root, native_dir)
        inject_bl_info_version(package_root / "__init__.py", blender_version)
        archive_path = build_zip(package_root, args.dist_dir.resolve(), args.package_name, version_string)

    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
