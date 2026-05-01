import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "services" / "_native_feature_support.py"


def load_support_module(*, ready_for_sync, verify_error=None, initial_native_status=None):
    package_name = "rig2testpkg_native_support"
    module_name = f"{package_name}.services._native_feature_support"
    proof_name = f"{package_name}.licensing._hmac_proof"
    registry_name = f"{package_name}.licensing.registry"
    manager_name = f"{package_name}.licensing.manager"
    feature_access_name = f"{package_name}.licensing.feature_access"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    services_pkg = types.ModuleType(f"{package_name}.services")
    services_pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []

    proof_mod = types.ModuleType(proof_name)
    proof_mod.compute_feature_proof = lambda feature_id, device_id: (1234567890, "proof-ok")

    registry_mod = types.ModuleType(registry_name)
    registry_mod.get_feature_spec = lambda feature_id: types.SimpleNamespace(
        integrity_targets=(("manager.py", "licensing/manager.py"),)
    )

    manager_mod = types.ModuleType(manager_name)
    manager_mod.get_license_manager = lambda: types.SimpleNamespace(get_device_id=lambda: "dev-123")

    feature_access_mod = types.ModuleType(feature_access_name)
    feature_access_mod.get_feature_status = lambda feature_name: {"effective_state": "needs_redownload"}
    feature_access_mod.is_feature_ready_for_native_sync = lambda feature_name: ready_for_sync

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.services"] = services_pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[proof_name] = proof_mod
    sys.modules[registry_name] = registry_mod
    sys.modules[manager_name] = manager_mod
    sys.modules[feature_access_name] = feature_access_mod

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    verify_calls = []
    set_calls = []
    native_status = dict(initial_native_status or {"authorized": False, "reason": ""})

    def verify_func(hashes):
        verify_calls.append(dict(hashes))
        if verify_error is not None:
            raise verify_error

    def get_license_status():
        return dict(native_status)

    def set_license_state(device_id, expires_at, hmac_proof):
        set_calls.append((device_id, expires_at, hmac_proof))

    return module, verify_calls, set_calls, verify_func, set_license_state, get_license_status


class NativeFeatureSupportTest(unittest.TestCase):
    def test_sync_authorizes_feature_when_pre_native_state_is_ready(self):
        module, verify_calls, set_calls, verify_func, set_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            set_license_state=set_license_state,
            verify_func=verify_func,
            get_license_status=get_license_status,
        )

        self.assertEqual(len(verify_calls), 1)
        self.assertEqual(set_calls[-1], ("dev-123", 1234567890, "proof-ok"))

    def test_sync_marks_invalid_when_integrity_verification_fails(self):
        module, verify_calls, set_calls, verify_func, set_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
            verify_error=RuntimeError("hash mismatch"),
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            set_license_state=set_license_state,
            verify_func=verify_func,
            get_license_status=get_license_status,
        )

        self.assertEqual(len(verify_calls), 1)
        self.assertEqual(set_calls[-1], ("", 0, "invalid"))

    def test_sync_does_not_reauthorize_after_native_integrity_failure(self):
        module, verify_calls, set_calls, verify_func, set_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
            initial_native_status={
                "authorized": False,
                "reason": "Face Capture integrity check failed: manager.py does not match the binary build.",
            },
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            set_license_state=set_license_state,
            verify_func=verify_func,
            get_license_status=get_license_status,
        )

        self.assertEqual(len(verify_calls), 1)
        self.assertEqual(set_calls, [])


if __name__ == "__main__":
    unittest.main()
