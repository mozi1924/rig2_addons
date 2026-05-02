#!/usr/bin/env python3
"""Shared native artifact metadata used by build, extract, verify, and upload scripts."""

from __future__ import annotations

import re
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "src" / "licensing" / "registry.py"
EXTENSIONS = (".so", ".pyd", ".dylib")
SIDECAR_SUFFIX = ".orbis.json"
_VERSION_SPECIFIC_FILENAME_RE = re.compile(r"(cpython-|\.cp\d{2,3}-)")


@dataclass(frozen=True)
class RuntimeArtifactSpec:
    runtime_tag: str
    platform: str
    arch: str
    artifact_name: str


@dataclass(frozen=True)
class ManagedNativeFeature:
    feature_id: str
    label: str
    native_module_name: str
    native_source_filename: str
    download_module_name: str
    service_getter: str


def _load_registry_module():
    spec = importlib.util.spec_from_file_location("rig2_native_artifacts_registry", REGISTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_managed_native_features() -> tuple[ManagedNativeFeature, ...]:
    registry = _load_registry_module()
    return tuple(
        ManagedNativeFeature(
            feature_id=spec.feature_id,
            label=spec.label,
            native_module_name=spec.native_module_name,
            native_source_filename=spec.native_source_filename,
            download_module_name=spec.download_module_name,
            service_getter=spec.service_getter,
        )
        for spec in registry.iter_native_feature_specs()
    )


MANAGED_NATIVE_FEATURES = _load_managed_native_features()
MODULE_NAMES = tuple(feature.native_module_name for feature in MANAGED_NATIVE_FEATURES)
MODULE_NAME_SET = frozenset(MODULE_NAMES)
MODULE_SOURCE_FILENAMES = {
    feature.native_module_name: feature.native_source_filename
    for feature in MANAGED_NATIVE_FEATURES
}


RUNTIME_ARTIFACT_SPECS = (
    RuntimeArtifactSpec("darwin-x86_64-abi3", "mac", "amd64", "mac.dylib"),
    RuntimeArtifactSpec("darwin-arm64-abi3", "mac", "arm64", "mac.dylib"),
    RuntimeArtifactSpec("linux-x86_64-abi3", "linux", "amd64", "linux.so"),
    RuntimeArtifactSpec("linux-arm64-abi3", "linux", "arm64", "linux.so"),
    RuntimeArtifactSpec("win32-x86_64-abi3", "win", "amd64", "win.pyd"),
    RuntimeArtifactSpec("win32-arm64-abi3", "win", "arm64", "win.pyd"),
)
RUNTIME_TAG_MAP = {spec.runtime_tag: spec for spec in RUNTIME_ARTIFACT_SPECS}


def parse_wheel_platform_tags(wheel_name: str) -> list[str]:
    if not wheel_name.endswith(".whl"):
        return []
    stem = wheel_name[:-4]
    parts = stem.split("-")
    if len(parts) < 5:
        return []
    return [tag for tag in parts[-1].split(".") if tag]


def map_wheel_platform_tag_to_runtime_tags(platform_tag: str) -> list[str]:
    tag = platform_tag.lower()

    if "macosx" in tag:
        if "universal2" in tag:
            return ["darwin-x86_64-abi3", "darwin-arm64-abi3"]
        if "x86_64" in tag:
            return ["darwin-x86_64-abi3"]
        if "arm64" in tag:
            return ["darwin-arm64-abi3"]

    if tag.startswith("win"):
        if "amd64" in tag or "x86_64" in tag:
            return ["win32-x86_64-abi3"]
        if "arm64" in tag:
            return ["win32-arm64-abi3"]

    if any(prefix in tag for prefix in ("manylinux", "musllinux", "linux")):
        if "x86_64" in tag or "amd64" in tag:
            return ["linux-x86_64-abi3"]
        if "aarch64" in tag or "arm64" in tag:
            return ["linux-arm64-abi3"]

    return []


def detect_module_name(filename: str) -> str:
    for module_name in MODULE_NAMES:
        if filename.startswith(module_name):
            return module_name
    return ""


def is_version_specific_binary(filename: str) -> bool:
    return bool(_VERSION_SPECIFIC_FILENAME_RE.search(filename.lower()))


def is_sidecar_metadata(filename: str) -> bool:
    return filename.lower().endswith(SIDECAR_SUFFIX)


def validate_runtime_layout(root: Path, *, require_complete_matrix: bool = False) -> list[str]:
    files = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    if not files:
        return ["no files found"]

    errors: list[str] = []
    tag_to_modules: dict[str, set[str]] = {}

    for rel in files:
        parts = rel.split("/")
        if len(parts) != 2:
            errors.append(f"unexpected depth: {rel}")
            continue

        runtime_tag, filename = parts
        spec = RUNTIME_TAG_MAP.get(runtime_tag)
        if spec is None:
            errors.append(f"unexpected tag: {rel}")
            continue

        module_name = detect_module_name(filename)
        if not module_name:
            errors.append(f"unexpected module name: {rel}")
            continue

        lowered = filename.lower()
        if is_sidecar_metadata(filename):
            continue
        if is_version_specific_binary(filename):
            errors.append(f"version-specific filename: {rel}")
        if not lowered.endswith(EXTENSIONS):
            errors.append(f"unexpected extension: {rel}")

        tag_to_modules.setdefault(runtime_tag, set()).add(module_name)

    expected_tags = tuple(RUNTIME_TAG_MAP)
    tags_to_check = expected_tags if require_complete_matrix else tuple(sorted(tag_to_modules))

    if require_complete_matrix:
        missing_tags = [tag for tag in expected_tags if tag not in tag_to_modules]
        for tag in missing_tags:
            errors.append(f"missing runtime tag: {tag}")

    for runtime_tag in tags_to_check:
        modules = tag_to_modules.get(runtime_tag, set())
        missing_modules = MODULE_NAME_SET - modules
        extra_modules = modules - MODULE_NAME_SET
        for module_name in sorted(missing_modules):
            errors.append(f"missing module for {runtime_tag}: {module_name}")
        for module_name in sorted(extra_modules):
            errors.append(f"unexpected module for {runtime_tag}: {module_name}")

    return errors
