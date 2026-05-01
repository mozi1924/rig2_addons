"""Centralized addon version metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[2] / "version.json"


@lru_cache(maxsize=1)
def load_version_info() -> dict[str, int]:
    with _VERSION_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    required_keys = ("major", "minor", "patch")
    info: dict[str, int] = {}
    for key in required_keys:
        value = data.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"Invalid version field '{key}': {value!r}")
        info[key] = value
    return info


def get_version_tuple() -> tuple[int, int, int]:
    info = load_version_info()
    return info["major"], info["minor"], info["patch"]


def get_version_string() -> str:
    return ".".join(str(part) for part in get_version_tuple())


MAJOR, MINOR, PATCH = get_version_tuple()
BL_INFO_VERSION = (MAJOR, MINOR, PATCH)
SEMVER = get_version_string()
