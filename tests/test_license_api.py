import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LICENSING_INIT_PATH = ROOT / "src" / "licensing" / "__init__.py"
LICENSING_API_PATH = ROOT / "src" / "licensing" / "api.py"


def _clear_test_package(package_name):
    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)


def _load_api_modules(*, manager, runtime_ready):
    package_name = "rig2testpkg_license_api"
    licensing_name = f"{package_name}.licensing"
    manager_name = f"{licensing_name}.manager"
    config_name = f"{licensing_name}.config"

    _clear_test_package(package_name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    licensing_pkg = types.ModuleType(licensing_name)
    licensing_pkg.__path__ = []

    manager_mod = types.ModuleType(manager_name)
    manager_mod.LicenseManager = object
    manager_mod.get_license_manager = lambda: manager

    config_mod = types.ModuleType(config_name)
    config_mod.HEARTBEAT_INTERVAL_SECONDS = 300
    config_mod.FEATURE_FACE_CAP = "face_cap"
    config_mod.FEATURE_MIFRAMES = "miframes"
    config_mod.FEATURE_R2BB = "r2bb"

    sys.modules[package_name] = pkg
    sys.modules[licensing_name] = licensing_pkg
    sys.modules[manager_name] = manager_mod
    sys.modules[config_name] = config_mod

    init_spec = importlib.util.spec_from_file_location(licensing_name, LICENSING_INIT_PATH)
    licensing_mod = importlib.util.module_from_spec(init_spec)
    assert init_spec is not None and init_spec.loader is not None
    sys.modules[licensing_name] = licensing_mod
    init_spec.loader.exec_module(licensing_mod)
    licensing_mod._LICENSE_RUNTIME_READY = bool(runtime_ready)

    api_name = f"{licensing_name}.api"
    api_spec = importlib.util.spec_from_file_location(api_name, LICENSING_API_PATH)
    api_mod = importlib.util.module_from_spec(api_spec)
    assert api_spec is not None and api_spec.loader is not None
    sys.modules[api_name] = api_mod
    api_spec.loader.exec_module(api_mod)
    return licensing_mod, api_mod


def _assert_primitives_only(testcase, value):
    primitive_types = (str, int, float, bool, type(None))
    if isinstance(value, primitive_types):
        return
    if isinstance(value, list):
        for item in value:
            _assert_primitives_only(testcase, item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            testcase.assertIsInstance(key, str)
            _assert_primitives_only(testcase, item)
        return
    testcase.fail(f"Non-primitive value leaked from public API: {type(value)!r}")


class LicenseApiTest(unittest.TestCase):
    def test_import_path_and_ready_provider_status(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=object()),
            get_status=lambda: {
                "activated": True,
                "product": "Rig2",
                "tier": "Pro",
                "features": {"miframes": True, "face_cap": False, "r2bb": True},
                "warnings": [{"level": "INFO", "message": "Heartbeat healthy", "action_required": False}],
            },
        )
        _licensing_mod, api_mod = _load_api_modules(manager=manager, runtime_ready=True)

        status = api_mod.get_provider_status()

        self.assertTrue(hasattr(api_mod, "get_provider_status"))
        self.assertTrue(hasattr(api_mod, "get_feature_access"))
        self.assertTrue(hasattr(api_mod, "is_feature_licensed"))
        self.assertEqual(api_mod.FEATURE_FACE_CAP, "face_cap")
        self.assertEqual(api_mod.FEATURE_MIFRAMES, "miframes")
        self.assertEqual(api_mod.FEATURE_R2BB, "r2bb")
        self.assertTrue(status["provider_available"])
        self.assertTrue(status["provider_ready"])
        self.assertTrue(status["activated"])
        self.assertEqual(status["reason"], "ok")
        self.assertEqual(status["features"], {"miframes": True, "face_cap": False, "r2bb": True})
        _assert_primitives_only(self, status)

    def test_feature_access_reports_unactivated_when_no_session(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=None),
            get_status=lambda: {
                "activated": False,
                "product": "",
                "tier": "",
                "features": {},
                "warnings": [],
            },
        )
        _licensing_mod, api_mod = _load_api_modules(manager=manager, runtime_ready=True)

        access = api_mod.get_feature_access(api_mod.FEATURE_MIFRAMES)

        self.assertFalse(access["available"])
        self.assertFalse(access["activated"])
        self.assertFalse(access["licensed"])
        self.assertEqual(access["reason"], "unactivated")
        _assert_primitives_only(self, access)

    def test_feature_access_reports_unlicensed_for_missing_feature_flag(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=object()),
            get_status=lambda: {
                "activated": True,
                "product": "Rig2",
                "tier": "Base",
                "features": {"miframes": False, "face_cap": False},
                "warnings": [],
            },
        )
        _licensing_mod, api_mod = _load_api_modules(manager=manager, runtime_ready=True)

        access = api_mod.get_feature_access(api_mod.FEATURE_MIFRAMES)

        self.assertFalse(access["available"])
        self.assertTrue(access["activated"])
        self.assertFalse(access["licensed"])
        self.assertEqual(access["reason"], "unlicensed")
        self.assertFalse(api_mod.is_feature_licensed(api_mod.FEATURE_MIFRAMES))

    def test_provider_status_reports_session_error_for_invalid_session(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=object()),
            get_status=lambda: {
                "activated": False,
                "product": "Rig2",
                "tier": "Pro",
                "features": {"miframes": True},
                "warnings": [{"level": "ERROR", "message": "Expired", "action_required": True}],
            },
        )
        _licensing_mod, api_mod = _load_api_modules(manager=manager, runtime_ready=True)

        status = api_mod.get_provider_status()
        access = api_mod.get_feature_access(api_mod.FEATURE_MIFRAMES)

        self.assertEqual(status["reason"], "session_error")
        self.assertEqual(access["reason"], "session_error")
        self.assertEqual(status["features"], {})

    def test_provider_status_reports_not_ready_before_registration(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=None),
            get_status=lambda: {
                "activated": False,
                "product": "",
                "tier": "",
                "features": {},
                "warnings": [],
            },
        )
        _licensing_mod, api_mod = _load_api_modules(manager=manager, runtime_ready=False)

        status = api_mod.get_provider_status()
        access = api_mod.get_feature_access(api_mod.FEATURE_MIFRAMES)

        self.assertTrue(status["provider_available"])
        self.assertFalse(status["provider_ready"])
        self.assertEqual(status["reason"], "provider_not_ready")
        self.assertEqual(access["reason"], "provider_not_ready")


if __name__ == "__main__":
    unittest.main()
