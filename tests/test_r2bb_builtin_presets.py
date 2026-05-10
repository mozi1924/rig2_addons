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
    package_name = "rig2testpkg_r2bb_builtin_presets"
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
    sys.modules[errors_module_name] = errors_mod
    sys.modules[service_module_name] = service_mod

    spec = importlib.util.spec_from_file_location(module_name, MAPPING_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _ExplodingService:
    def is_feature_unlocked(self):
        raise RuntimeError("service unavailable")


class R2BBBuiltinPresetTest(unittest.TestCase):
    def test_builtin_enum_includes_default_and_march(self):
        mapping_mod = _load_mapping_module(service_factory=lambda: _ExplodingService())
        ids = [item[0] for item in mapping_mod.get_preset_enum_items(include_current=False)]

        self.assertIn(mapping_mod.DEFAULT_PRESET_ID, ids)
        self.assertIn(mapping_mod.MARCH_PRESET_ID, ids)

    def test_march_builtin_preset_loads_without_backend_service(self):
        mapping_mod = _load_mapping_module(service_factory=lambda: _ExplodingService())
        preset = mapping_mod.load_preset_definition(mapping_mod.MARCH_PRESET_ID)

        self.assertIsNotNone(preset)
        self.assertTrue(preset["builtin"])
        self.assertGreater(len(preset["entries"]), 0)

        head_entry = next((item for item in preset["entries"] if item.get("mi_bone") == "MI_Head"), None)
        self.assertIsNotNone(head_entry)
        self.assertEqual(head_entry.get("export_name"), "head")


if __name__ == "__main__":
    unittest.main()
