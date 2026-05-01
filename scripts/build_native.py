#!/usr/bin/env python3
"""Build Rig2 native C++ backends into src/native/binaries/*.

Default behavior (when setuptools is available) builds ABI3 modules and copies to:
- <platform-tag>
- <sys.platform>-abi3
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_CPP_DIR = ROOT / "native_cpp"
MODULE_NAMES = ("rig2_miframes", "rig2_face_cap")


def _run_script(rel_path: str) -> None:
    """Run a Python helper script from the repo root."""
    script_path = ROOT / rel_path
    subprocess.check_call([sys.executable, str(script_path)], cwd=str(ROOT))


def platform_tag() -> str:
    return f"{sys.platform}-{arch_tag()}-{sys.version_info.major}{sys.version_info.minor}"


def legacy_platform_tag() -> str:
    return f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"


def arch_tag() -> str:
    machine = (platform.machine() or "").strip().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def abi3_platform_tag() -> str:
    return f"{sys.platform}-{arch_tag()}-abi3"


def legacy_abi3_platform_tag() -> str:
    return f"{sys.platform}-abi3"


def extension_suffixes() -> list[str]:
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None)
    if suffixes:
        return list(suffixes)
    return [".so", ".pyd", ".dylib"]


def ensure_build_backend_available() -> None:
    if importlib.util.find_spec("setuptools") is not None:
        return
    if importlib.util.find_spec("distutils.core") is not None:
        return
    raise RuntimeError(
        "This Python runtime does not provide setuptools/distutils. "
        "Use a Python with build tooling (for example Blender's python3.11 or system python3.9)."
    )


def build_extensions() -> None:
    subprocess.check_call(
        [sys.executable, "setup.py", "build_ext", "--inplace", "--force"],
        cwd=str(NATIVE_CPP_DIR),
    )


def find_built_module(module_name: str) -> Path:
    abi3_candidates = sorted(NATIVE_CPP_DIR.glob(f"{module_name}*.abi3.*"))
    if abi3_candidates:
        return abi3_candidates[0]

    suffixes = extension_suffixes()
    for suffix in suffixes:
        candidate = NATIVE_CPP_DIR / f"{module_name}{suffix}"
        if candidate.exists():
            return candidate

    fallback = sorted(NATIVE_CPP_DIR.glob(f"{module_name}*.so"))
    if fallback:
        return fallback[0]

    raise FileNotFoundError(f"Built extension for '{module_name}' not found in {NATIVE_CPP_DIR}")


def _is_abi3_binary(module_path: Path) -> bool:
    return ".abi3." in module_path.name


def _clear_existing_variants(output_dir: Path, module_name: str) -> None:
    for existing in output_dir.glob(f"{module_name}*"):
        if existing.is_file():
            existing.unlink()


def _copy_to_platform_dir(module_path: Path, tag: str, module_name: str) -> Path:
    output_dir = ROOT / "src" / "native" / "binaries" / tag
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_existing_variants(output_dir, module_name)
    output_path = output_dir / module_path.name
    shutil.copy2(module_path, output_path)
    return output_path


def copy_to_runtime_bins(module_path: Path, module_name: str) -> list[Path]:
    copied = []
    copied.append(_copy_to_platform_dir(module_path, platform_tag(), module_name))
    copied.append(_copy_to_platform_dir(module_path, legacy_platform_tag(), module_name))
    if _is_abi3_binary(module_path):
        copied.append(_copy_to_platform_dir(module_path, abi3_platform_tag(), module_name))
        copied.append(_copy_to_platform_dir(module_path, legacy_abi3_platform_tag(), module_name))
    deduped = []
    seen = set()
    for path in copied:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def main() -> int:
    print(f"[rig2-native] Python: {sys.executable}")
    print(f"[rig2-native] Arch tag: {arch_tag()}")
    print(f"[rig2-native] Platform tag: {platform_tag()}")
    print(f"[rig2-native] Legacy platform tag: {legacy_platform_tag()}")
    print(f"[rig2-native] ABI3 tag: {abi3_platform_tag()}")
    print(f"[rig2-native] Legacy ABI3 tag: {legacy_abi3_platform_tag()}")

    # Generate integrity hashes header before compilation.
    _run_script("scripts/generate_integrity_hashes.py")

    ensure_build_backend_available()
    build_extensions()

    for module_name in MODULE_NAMES:
        built = find_built_module(module_name)
        copied_paths = copy_to_runtime_bins(built, module_name)
        for copied in copied_paths:
            print(f"[rig2-native] {module_name}: {copied}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
