import importlib.util
import importlib.machinery
import os
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Optional


def get_native_root():
    """Return the directory where downloaded native modules should live."""
    return os.path.join(os.path.dirname(__file__), "binaries")


def get_platform_tag():
    return f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"


@dataclass(frozen=True)
class NativeLoadResult:
    module_name: str
    module: Optional[ModuleType]
    module_path: str
    error: str

    @property
    def is_available(self):
        return self.module is not None


def build_native_module_path(module_name):
    # `EXTENSION_SUFFIXES` lives in importlib.machinery across Python versions.
    # Keep a small fallback list for maximum compatibility.
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None) or [".so", ".pyd", ".dylib"]
    base_dir = os.path.join(get_native_root(), get_platform_tag())
    for suffix in suffixes:
        yield os.path.join(base_dir, module_name + suffix)


def load_native_extension_result(module_name):
    """Try loading a managed native extension and return a structured status."""
    checked_paths = list(build_native_module_path(module_name))
    existing_paths = [module_path for module_path in checked_paths if os.path.exists(module_path)]
    if not existing_paths:
        return NativeLoadResult(
            module_name=module_name,
            module=None,
            module_path="",
            error=f"Native backend is locked: missing binary for '{module_name}' on platform '{get_platform_tag()}'.",
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


def load_native_extension(module_name):
    """
    Attempt to load a native extension module from the managed binary directory.
    Returns the imported module or None if no compatible binary is available.
    """
    return load_native_extension_result(module_name).module


def load_native_or_fallback(native_name, fallback_importer):
    native_module = load_native_extension(native_name)
    if native_module is not None:
        return native_module, True

    fallback_module = fallback_importer()
    return fallback_module, False
