#!/usr/bin/env python3
"""Extract native extension modules from cibuildwheel-produced wheels.

Reads .whl files from a wheelhouse directory, extracts the native
.pyd/.so/.dylib files, and places them into a runtime-compatible
directory layout:

    <output>/
      darwin-arm64-abi3/
        rig2_face_cap.abi3.so
        rig2_miframes.abi3.so
        rig2_r2bb.abi3.so
      darwin-x86_64-abi3/
        ...
      linux-x86_64-abi3/
        ...
      linux-arm64-abi3/
        ...
      win32-x86_64-abi3/
        ...
      win32-arm64-abi3/
        ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# Ensure the scripts directory is on sys.path so we can import native_artifacts.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from native_artifacts import (
    MODULE_NAMES,
    MODULE_NAME_SET,
    RUNTIME_TAG_MAP,
    detect_module_name,
    map_wheel_platform_tag_to_runtime_tags,
    parse_wheel_platform_tags,
)


def _is_native_module(filename: str) -> bool:
    """Return True if *filename* is a native extension for a managed module."""
    return bool(detect_module_name(filename))


def _find_native_files(wheel_dir: Path) -> dict[str, Path]:
    """Find native extension files inside an extracted wheel directory.

    Returns a mapping of module_name → path.
    """
    found: dict[str, Path] = {}
    for root, _dirs, files in os.walk(wheel_dir):
        for fname in files:
            if not _is_native_module(fname):
                continue
            full = Path(root) / fname
            mod_name = detect_module_name(fname)
            if mod_name:
                found[mod_name] = full
    return found


def extract_wheels(wheelhouse: Path, output: Path) -> None:
    """Extract native modules from all wheels and place into output dir."""
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"No .whl files found in {wheelhouse}")

    output.mkdir(parents=True, exist_ok=True)
    written = 0
    seen_tags: set[str] = set()

    for wheel_path in wheels:
        wheel_tags = parse_wheel_platform_tags(wheel_path.name)
        runtime_tags: list[str] = []
        for tag in wheel_tags:
            runtime_tags.extend(map_wheel_platform_tag_to_runtime_tags(tag))

        if not runtime_tags:
            print(f"  [SKIP] {wheel_path.name} — no matching runtime tags")
            continue

        # Deduplicate while preserving order
        runtime_tags = list(dict.fromkeys(runtime_tags))

        with tempfile.TemporaryDirectory(prefix="rig2-wheel-extract-") as tmp:
            with zipfile.ZipFile(wheel_path, "r") as zf:
                zf.extractall(tmp)
            native_files = _find_native_files(Path(tmp))

            if not native_files:
                print(f"  [SKIP] {wheel_path.name} — no managed native modules found")
                continue

            # Copy files immediately while temp dir still exists
            for rt_tag in runtime_tags:
                spec = RUNTIME_TAG_MAP.get(rt_tag)
                if spec is None:
                    print(f"  [WARN] {wheel_path.name} → unknown runtime tag '{rt_tag}', skipping")
                    continue
                tag_dir = output / rt_tag
                tag_dir.mkdir(parents=True, exist_ok=True)
                seen_tags.add(rt_tag)

                for mod_name, src_path in sorted(native_files.items()):
                    dest = tag_dir / src_path.name
                    shutil.copy2(src_path, dest)
                    written += 1

            print(f"  {wheel_path.name} → {', '.join(runtime_tags)} ({len(native_files)} modules)")

    print(f"\nExtracted {written} native modules across {len(seen_tags)} runtime tags.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract native extension modules from cibuildwheel-produced wheels."
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        required=True,
        help="Directory containing .whl files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Directory where extracted native modules will be placed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.wheelhouse.exists():
        raise SystemExit(f"Wheelhouse directory does not exist: {args.wheelhouse}")
    extract_wheels(args.wheelhouse, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
