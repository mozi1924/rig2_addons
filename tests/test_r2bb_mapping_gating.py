import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "src" / "modules" / "r2bb" / "mapping.py"


def _install_stub_bpy():
    bpy = types.ModuleType("bpy")
    bpy.utils = types.SimpleNamespace(
        user_resource=lambda *_args, **_kwargs: "",
    )
    sys.modules["bpy"] = bpy


def _load_mapping_module(*, service_factory):
    package_name = "rig2testpkg_r2bb_mapping"
    module_name = f"{package_name}.modules.r2bb.mapping"
    service_module_name = f"{package_name}.services.r2bb_service"
    errors_module_name = f"{package_name}.services.errors"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    _install_stub_bpy()

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    modules_pkg = types.ModuleType(f"{package_name}.modules")
    modules_pkg.__path__ = []
    r2bb_pkg = types.ModuleType(f"{package_name}.modules.r2bb")
    r2bb_pkg.__path__ = []
    services_pkg = types.ModuleType(f"{package_name}.services")
    services_pkg.__path__ = []
    i18n_mod = types.ModuleType(f"{package_name}.i18n")
    i18n_mod.iface = lambda text, **_kwargs: str(text)
    i18n_mod.format_text = lambda text, **kwargs: str(text).format(**kwargs) if kwargs else str(text)

    errors_mod = types.ModuleType(errors_module_name)

    class FeatureLockedError(RuntimeError):
        pass

    errors_mod.FeatureLockedError = FeatureLockedError

    service_mod = types.ModuleType(service_module_name)
    service_mod.get_r2bb_backend_service = service_factory

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.modules"] = modules_pkg
    sys.modules[f"{package_name}.modules.r2bb"] = r2bb_pkg
    sys.modules[f"{package_name}.services"] = services_pkg
    sys.modules[f"{package_name}.i18n"] = i18n_mod
    sys.modules[errors_module_name] = errors_mod
    sys.modules[service_module_name] = service_mod

    spec = importlib.util.spec_from_file_location(module_name, MAPPING_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, FeatureLockedError


class _LockedService:
    def is_feature_unlocked(self):
        return False

    def get_feature_status(self):
        return {"message": "R2BB is not included in the current license tier."}

    def get_lock_reason(self):
        return "R2BB is locked"


class _ExplodingService:
    def is_feature_unlocked(self):
        raise RuntimeError("service unavailable")


class R2BBMappingGatingTest(unittest.TestCase):
    def test_locked_license_does_not_fall_back_to_python_mapping_helpers(self):
        mapping_mod, FeatureLockedError = _load_mapping_module(
            service_factory=lambda: _LockedService(),
        )

        with self.assertRaises(FeatureLockedError):
            mapping_mod.mapping_entries_to_pairs([
                {"base_bone": "Base", "mi_bone": "MI"},
            ])

    def test_unexpected_service_failure_does_not_fall_back_to_python_mapping_helpers(self):
        mapping_mod, _FeatureLockedError = _load_mapping_module(
            service_factory=lambda: _ExplodingService(),
        )

        with self.assertRaises(RuntimeError):
            mapping_mod.mapping_entries_to_pairs([
                {"base_bone": "Base", "mi_bone": "MI"},
            ])


if __name__ == "__main__":
    unittest.main()
