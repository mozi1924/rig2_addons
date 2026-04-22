import importlib.util
import os
import sys
from types import ModuleType


def get_native_root():
    """Return the directory where downloaded native modules should live."""
    return os.path.join(os.path.dirname(__file__), "binaries")


def get_platform_tag():
    return f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"


def build_native_module_path(module_name):
    suffixes = importlib.util.EXTENSION_SUFFIXES or [".so"]
    base_dir = os.path.join(get_native_root(), get_platform_tag())
    for suffix in suffixes:
        yield os.path.join(base_dir, module_name + suffix)


def load_native_extension(module_name):
    """
    Attempt to load a native extension module from the managed binary directory.
    Returns the imported module or None if no compatible binary is available.
    """
    for module_path in build_native_module_path(module_name):
        if not os.path.exists(module_path):
            continue

        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return None


def load_native_or_fallback(native_name, fallback_importer):
    native_module = load_native_extension(native_name)
    if native_module is not None:
        return native_module, True

    fallback_module = fallback_importer()
    return fallback_module, False

