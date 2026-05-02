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

from native_artifacts import MODULE_NAMES

ROOT = Path(__file__).resolve().parents[1]
NATIVE_CPP_DIR = ROOT / "native_cpp"
_REEXEC_GUARD_ENV = "RIG2_BUILD_NATIVE_REEXEC"
_BUILD_PYTHON_ENV = "RIG2_BUILD_PYTHON"


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
    try:
        if importlib.util.find_spec("distutils.core") is not None:
            return
    except ModuleNotFoundError:
        pass
    raise RuntimeError(
        "This Python runtime does not provide setuptools/distutils. "
        "Use a Python with build tooling (for example Blender's python3.11 or system python3.9)."
    )


def _candidate_build_pythons() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get(_BUILD_PYTHON_ENV, "").strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(ROOT / ".venv-build" / "bin" / "python3")
    candidates.append(ROOT / ".venv-build" / "bin" / "python")
    return candidates


def _can_use_build_python(python_path: Path) -> bool:
    if not python_path.exists():
        return False
    try:
        subprocess.check_call(
            [
                str(python_path),
                "-c",
                "import setuptools, wheel",
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return True


def maybe_reexec_with_build_python() -> None:
    if os.environ.get(_REEXEC_GUARD_ENV) == "1":
        return
    try:
        ensure_build_backend_available()
        return
    except RuntimeError:
        pass

    for python_path in _candidate_build_pythons():
        if not _can_use_build_python(python_path):
            continue
        env = dict(os.environ)
        env[_REEXEC_GUARD_ENV] = "1"
        print(f"[rig2-native] Re-running with build Python: {python_path}")
        raise SystemExit(
            subprocess.call(
                [str(python_path), str(Path(__file__).resolve())],
                cwd=str(ROOT),
                env=env,
            )
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


def _clear_all_runtime_variants(module_name: str) -> None:
    native_root = ROOT / "src" / "native" / "binaries"
    if not native_root.exists():
        return
    for existing in native_root.rglob(f"{module_name}*"):
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
    _clear_all_runtime_variants(module_name)
    # Always publish to abi3 runtime tag so loader/distribution paths stay stable
    # across local builds (even when setuptools emits plain ".pyd"/".so" names).
    target_tag = abi3_platform_tag()
    return [_copy_to_platform_dir(module_path, target_tag, module_name)]


def main() -> int:
    maybe_reexec_with_build_python()
    print(f"[rig2-native] Python: {sys.executable}")
    print(f"[rig2-native] Arch tag: {arch_tag()}")
    print(f"[rig2-native] Platform tag: {platform_tag()}")
    print(f"[rig2-native] Legacy platform tag: {legacy_platform_tag()}")
    print(f"[rig2-native] ABI3 tag: {abi3_platform_tag()}")
    print(f"[rig2-native] Legacy ABI3 tag: {legacy_abi3_platform_tag()}")

    # Generate integrity hashes header before compilation.
    _run_script("scripts/generate_orbisauth_trust.py")
    _run_script("scripts/generate_integrity_hashes.py")

    ensure_build_backend_available()
    build_extensions()

    for module_name in MODULE_NAMES:
        built = find_built_module(module_name)
        copied_paths = copy_to_runtime_bins(built, module_name)
        for copied in copied_paths:
            print(f"[rig2-native] {module_name}: {copied}")

    _run_script("scripts/generate_native_manifests.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
