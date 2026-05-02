import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "services" / "native_feature_service.py"


def load_service_module(*, feature_status, native_status):
    package_name = "rig2testpkg_native_service"
    module_name = f"{package_name}.services.native_feature_service"
    feature_access_name = f"{package_name}.licensing.feature_access"
    registry_name = f"{package_name}.licensing.registry"
    licensed_wrapper_name = f"{package_name}.native.licensed_wrapper"
    support_name = f"{package_name}.services._native_feature_support"
    errors_name = f"{package_name}.services.errors"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []
    native_pkg = types.ModuleType(f"{package_name}.native")
    native_pkg.__path__ = []
    services_pkg = types.ModuleType(f"{package_name}.services")
    services_pkg.__path__ = []

    feature_access_mod = types.ModuleType(feature_access_name)
    feature_access_mod.get_feature_status = lambda feature_id: dict(feature_status)

    registry_mod = types.ModuleType(registry_name)
    registry_mod.get_feature_spec = lambda feature_id: types.SimpleNamespace(
        feature_id=feature_id,
        label="Face Capture",
    )

    wrapper = types.SimpleNamespace(
        backend=lambda: "backend",
        is_native_backend=lambda: True,
        get_license_status=lambda: dict(native_status),
        get_lock_reason=lambda: "locked",
        apply_native_grant=lambda *args, **kwargs: None,
        clear_license_state=lambda: None,
    )
    licensed_wrapper_mod = types.ModuleType(licensed_wrapper_name)
    licensed_wrapper_mod.get_native_wrapper = lambda feature_id: wrapper

    support_mod = types.ModuleType(support_name)
    support_mod.get_feature_lock_reason = lambda **kwargs: "fallback"
    support_mod.sync_license_state_to_native = lambda **kwargs: None
    support_mod.native_reason_requires_redownload = lambda reason: any(
        marker in str(reason or "").lower()
        for marker in (
            "integrity check failed",
            "digest mismatch",
            "size mismatch",
            "artifact manifest",
            "manifest mismatch",
            "module mismatch",
            "binary validation failed",
            "source root not found",
            "missing file",
            "authorization state is unavailable",
        )
    )

    errors_mod = types.ModuleType(errors_name)

    class FeatureLockedError(Exception):
        pass

    errors_mod.FeatureLockedError = FeatureLockedError

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[f"{package_name}.native"] = native_pkg
    sys.modules[f"{package_name}.services"] = services_pkg
    sys.modules[feature_access_name] = feature_access_mod
    sys.modules[registry_name] = registry_mod
    sys.modules[licensed_wrapper_name] = licensed_wrapper_mod
    sys.modules[support_name] = support_mod
    sys.modules[errors_name] = errors_mod

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class NativeFeatureServiceTest(unittest.TestCase):
    def test_sync_pending_native_state_stays_warning_and_locked(self):
        module = load_service_module(
            feature_status={
                "effective_state": "ready",
                "message": "Face Capture is ready.",
                "action": "",
                "can_download": False,
                "can_retry": False,
            },
            native_status={"authorized": False, "reason": "", "expires_at": 0},
        )

        service = module.NativeLicensedFeatureService("face_cap", logging.getLogger("test"))
        status = service.get_feature_status()

        self.assertEqual(status["effective_state"], "session_warning")
        self.assertEqual(status["message"], "Face Capture native authorization is syncing.")
        self.assertFalse(status["native_authorized"])
        self.assertFalse(service.is_feature_unlocked())

    def test_expired_native_state_does_not_force_redownload(self):
        module = load_service_module(
            feature_status={
                "effective_state": "ready",
                "message": "Face Capture is ready.",
                "action": "",
                "can_download": False,
                "can_retry": False,
            },
            native_status={
                "authorized": False,
                "reason": "native grant expired; sync your license",
                "expires_at": 0,
            },
        )

        service = module.NativeLicensedFeatureService("face_cap", logging.getLogger("test"))
        status = service.get_feature_status()

        self.assertEqual(status["effective_state"], "session_warning")
        self.assertIn("expired", status["message"])
        self.assertFalse(status["can_download"])

    def test_digest_mismatch_requires_redownload(self):
        module = load_service_module(
            feature_status={
                "effective_state": "ready",
                "message": "Face Capture is ready.",
                "action": "",
                "can_download": False,
                "can_retry": False,
            },
            native_status={
                "authorized": False,
                "reason": "artifact digest mismatch for rig2_face_cap.abi3.so",
                "expires_at": 0,
                "needs_redownload": True,
            },
        )

        service = module.NativeLicensedFeatureService("face_cap", logging.getLogger("test"))
        status = service.get_feature_status()

        self.assertEqual(status["effective_state"], "needs_redownload")
        self.assertTrue(status["can_download"])
        self.assertFalse(service.is_feature_unlocked())

    def test_empty_native_status_requires_redownload(self):
        module = load_service_module(
            feature_status={
                "effective_state": "ready",
                "message": "Face Capture is ready.",
                "action": "",
                "can_download": False,
                "can_retry": False,
            },
            native_status={},
        )

        service = module.NativeLicensedFeatureService("face_cap", logging.getLogger("test"))
        status = service.get_feature_status()

        self.assertEqual(status["effective_state"], "needs_redownload")
        self.assertIn("authorization state is unavailable", status["message"].lower())
        self.assertFalse(status["native_authorized"])
        self.assertFalse(service.is_feature_unlocked())


if __name__ == "__main__":
    unittest.main()
