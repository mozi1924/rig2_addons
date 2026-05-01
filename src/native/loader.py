import importlib.util
import importlib.machinery
import os
import platform
import pathlib
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Optional, Sequence


def get_native_root():
    """Return the directory where downloaded native modules should live."""
    return os.environ.get("RIG2_NATIVE_ROOT") or os.path.join(os.path.dirname(__file__), "binaries")



def get_platform_tag():
    return f"{sys.platform}-{get_arch_tag()}-{sys.version_info.major}{sys.version_info.minor}"


def get_legacy_platform_tag():
    """Legacy runtime tag kept for backward compatibility."""
    return f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"


def get_arch_tag():
    machine = (platform.machine() or "").strip().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def get_abi3_platform_tag():
    return f"{sys.platform}-{get_arch_tag()}-abi3"


def get_legacy_abi3_platform_tag():
    """Legacy abi3 tag kept for backward compatibility."""
    return f"{sys.platform}-abi3"


def get_platform_tags():
    """Return search-order platform tags for native binary discovery."""
    tags = [
        get_abi3_platform_tag(),
        get_legacy_abi3_platform_tag(),
        get_platform_tag(),
        get_legacy_platform_tag(),
    ]
    # Preserve order while deduplicating.
    return tuple(dict.fromkeys(tags))


def get_extension_suffixes():
    """Return extension suffixes, preferring ABI3-compatible names first."""
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None) or [".so", ".pyd", ".dylib"]
    ordered = sorted(
        suffixes,
        key=lambda suffix: (0 if ".abi3." in suffix else 1, len(suffix)),
    )
    return tuple(dict.fromkeys(ordered))


def get_preferred_extension_suffix():
    """Return the canonical suffix used for managed native binaries."""
    suffixes = get_extension_suffixes()
    return suffixes[0] if suffixes else ".so"


def get_primary_native_module_path(module_name):
    return os.path.join(
        get_native_root(),
        get_abi3_platform_tag(),
        module_name + get_preferred_extension_suffix(),
    )


def list_existing_native_module_paths(module_name):
    """Return every on-disk variant for a managed native module."""
    native_root = pathlib.Path(get_native_root())
    if not native_root.exists():
        return ()

    suffixes = get_extension_suffixes()
    suffix_set = set(suffixes)
    matches = []
    for path in native_root.rglob(f"{module_name}*"):
        if not path.is_file():
            continue
        if any(str(path).endswith(suffix) for suffix in suffix_set):
            matches.append(str(path))
    return tuple(sorted(dict.fromkeys(matches)))


def get_residual_native_module_paths(module_name):
    """Return unexpected leftover variants outside the canonical path."""
    primary_path = os.path.normpath(get_primary_native_module_path(module_name))
    return tuple(
        path
        for path in list_existing_native_module_paths(module_name)
        if os.path.normpath(path) != primary_path
    )


@dataclass(frozen=True)
class NativeLoadResult:
    module_name: str
    module: Optional[ModuleType]
    module_path: str
    error: str

    @property
    def is_available(self):
        return self.module is not None


def _format_validation_error(
    module_name,
    module_path,
    missing_callables,
    missing_attributes,
    api_version_attr,
    expected_api_version,
    actual_api_version,
):
    parts = []
    if missing_callables:
        parts.append(
            "missing callables: " + ", ".join(sorted(missing_callables))
        )
    if missing_attributes:
        parts.append(
            "missing attributes: " + ", ".join(sorted(missing_attributes))
        )
    if expected_api_version is not None:
        parts.append(
            f"{api_version_attr} expected {expected_api_version}, got {actual_api_version!r}"
        )

    joined = "; ".join(parts) if parts else "interface validation failed"
    return (
        "Native backend is locked: "
        f"'{module_name}' at '{module_path}' failed validation ({joined})."
    )


def _validate_native_module_interface(
    *,
    module_name,
    module,
    module_path,
    required_callables,
    required_attributes,
    api_version_attr,
    expected_api_version,
):
    missing_callables = []
    missing_attributes = []

    for symbol in required_callables:
        if not callable(getattr(module, symbol, None)):
            missing_callables.append(symbol)

    for symbol in required_attributes:
        if not hasattr(module, symbol):
            missing_attributes.append(symbol)

    actual_api_version = getattr(module, api_version_attr, None)
    version_mismatch = (
        expected_api_version is not None
        and actual_api_version != expected_api_version
    )

    if missing_callables or missing_attributes or version_mismatch:
        return _format_validation_error(
            module_name=module_name,
            module_path=module_path,
            missing_callables=missing_callables,
            missing_attributes=missing_attributes,
            api_version_attr=api_version_attr,
            expected_api_version=expected_api_version,
            actual_api_version=actual_api_version,
        )
    return ""


def build_native_module_path(module_name):
    suffixes = get_extension_suffixes()
    for platform_tag in get_platform_tags():
        base_dir = os.path.join(get_native_root(), platform_tag)
        for suffix in suffixes:
            yield os.path.join(base_dir, module_name + suffix)


def load_native_extension_result(
    module_name,
    *,
    required_callables: Sequence[str] = (),
    required_attributes: Sequence[str] = (),
    api_version_attr: str = "RIG2_API_VERSION",
    expected_api_version: Optional[int] = None,
):
    """Try loading a managed native extension and return a structured status."""
    checked_paths = list(build_native_module_path(module_name))
    existing_paths = [module_path for module_path in checked_paths if os.path.exists(module_path)]

    if not existing_paths:
        tags = ", ".join(get_platform_tags())
        return NativeLoadResult(
            module_name=module_name,
            module=None,
            module_path="",
            error=(
                "Native backend is locked: missing binary for "
                f"'{module_name}' on platform tags [{tags}]."
            ),
        )

    last_error = ""
    for module_path in build_native_module_path(module_name):
        if not os.path.exists(module_path):
            continue

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                last_error = f"Native backend is locked: could not create import spec for '{module_path}'."
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            validation_error = _validate_native_module_interface(
                module_name=module_name,
                module=module,
                module_path=module_path,
                required_callables=required_callables,
                required_attributes=required_attributes,
                api_version_attr=api_version_attr,
                expected_api_version=expected_api_version,
            )
            if validation_error:
                last_error = validation_error
                continue

            return NativeLoadResult(
                module_name=module_name,
                module=module,
                module_path=module_path,
                error="",
            )
        except Exception as exc:
            last_error = f"Native backend is locked: failed to load '{module_path}': {exc}"

    return NativeLoadResult(
        module_name=module_name,
        module=None,
        module_path=existing_paths[0] if existing_paths else "",
        error=last_error or f"Native backend is locked: failed to load '{module_name}'.",
    )
