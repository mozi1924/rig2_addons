#!/usr/bin/env python3
"""Utilities for Rig2 semantic version management."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "version.json"
INIT_FILE = ROOT / "__init__.py"
VERSION_KEYS = ("major", "minor", "patch")


def load_version_info(version_file: Path = VERSION_FILE) -> dict[str, int]:
    with version_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    version: dict[str, int] = {}
    for key in VERSION_KEYS:
        value = data.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"Invalid version field '{key}': {value!r}")
        version[key] = value
    return version


def save_version_info(version: dict[str, int], version_file: Path = VERSION_FILE) -> None:
    payload = {key: int(version[key]) for key in VERSION_KEYS}
    with version_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sync_bl_info_version(version: dict[str, int], init_file: Path = INIT_FILE) -> None:
    content = init_file.read_text(encoding="utf-8")
    replacement = f'"version": {version_tuple(version)},'
    updated, count = re.subn(
        r'"version":\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\),',
        replacement,
        content,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Could not locate literal bl_info version in {init_file}")
    init_file.write_text(updated, encoding="utf-8")


def version_tuple(version: dict[str, int]) -> tuple[int, int, int]:
    return tuple(version[key] for key in VERSION_KEYS)


def semver(version: dict[str, int]) -> str:
    return ".".join(str(version[key]) for key in VERSION_KEYS)


def bump_version(version: dict[str, int], part: str) -> dict[str, int]:
    updated = dict(version)
    if part == "major":
        updated["major"] += 1
        updated["minor"] = 0
        updated["patch"] = 0
    elif part == "minor":
        updated["minor"] += 1
        updated["patch"] = 0
    elif part == "patch":
        updated["patch"] += 1
    else:
        raise ValueError(f"Unsupported version part: {part}")
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Rig2 addon semantic version.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Print the current version.")
    show_parser.add_argument(
        "--format",
        choices=("semver", "blender", "json"),
        default="semver",
        help="Output format.",
    )

    set_parser = subparsers.add_parser("set", help="Set the full semantic version.")
    for key in VERSION_KEYS:
        set_parser.add_argument(f"--{key}", type=int, required=True)

    bump_parser = subparsers.add_parser("bump", help="Bump one semantic version part.")
    bump_parser.add_argument("part", choices=VERSION_KEYS)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current = load_version_info()

    if args.command == "show":
        if args.format == "semver":
            print(semver(current))
        elif args.format == "blender":
            print(version_tuple(current))
        else:
            print(json.dumps(current, ensure_ascii=True))
        return 0

    if args.command == "set":
        updated = {key: getattr(args, key) for key in VERSION_KEYS}
    else:
        updated = bump_version(current, args.part)

    save_version_info(updated)
    sync_bl_info_version(updated)
    print(semver(updated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
