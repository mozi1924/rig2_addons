#!/usr/bin/env python3
"""Build Rig2 native C++ backends into src/native/binaries/<platform-tag>."""

from __future__ import annotations

import importlib.machinery
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_CPP_DIR = ROOT / "native_cpp"
MODULE_NAMES = ("rig2_miframes", "rig2_face_cap")


def platform_tag() -> str:
    return f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"


def extension_suffixes() -> list[str]:
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None)
    if suffixes:
        return list(suffixes)
    return [".so", ".pyd", ".dylib"]


def build_extensions() -> None:
    subprocess.check_call(
        [sys.executable, "setup.py", "build_ext", "--inplace", "--force"],
        cwd=str(NATIVE_CPP_DIR),
    )


def find_built_module(module_name: str) -> Path:
    suffixes = extension_suffixes()
    for suffix in suffixes:
        candidate = NATIVE_CPP_DIR / f"{module_name}{suffix}"
        if candidate.exists():
            return candidate

    fallback = sorted(NATIVE_CPP_DIR.glob(f"{module_name}*.so"))
    if fallback:
        return fallback[0]

    raise FileNotFoundError(f"Built extension for '{module_name}' not found in {NATIVE_CPP_DIR}")


def copy_to_runtime_bin(module_path: Path) -> Path:
    output_dir = ROOT / "src" / "native" / "binaries" / platform_tag()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / module_path.name
    shutil.copy2(module_path, output_path)
    return output_path


def main() -> int:
    print(f"[rig2-native] Python: {sys.executable}")
    print(f"[rig2-native] Platform tag: {platform_tag()}")
    build_extensions()

    for module_name in MODULE_NAMES:
        built = find_built_module(module_name)
        copied = copy_to_runtime_bin(built)
        print(f"[rig2-native] {module_name}: {copied}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
