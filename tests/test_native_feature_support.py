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
    manager_name = f"{package_name}.licensing.manager"
    feature_access_name = f"{package_name}.licensing.feature_access"
    jwt_name = f"{package_name}.orbisauth._jwt"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    services_pkg = types.ModuleType(f"{package_name}.services")
    services_pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []
    orbisauth_pkg = types.ModuleType(f"{package_name}.orbisauth")
    orbisauth_pkg.__path__ = []
    jwt_mod = types.ModuleType(jwt_name)
    jwt_mod.fetch_jwks = lambda server_url, timeout=30.0: {"keys": [{"kid": "test-key"}]}

    manager_mod = types.ModuleType(manager_name)
    manager_mod.get_license_manager = lambda: types.SimpleNamespace(
        request_native_grant=lambda feature_id: types.SimpleNamespace(grant_token="grant-ok"),
        _client=types.SimpleNamespace(server_url="https://example.invalid", timeout_seconds=5.0),
    )

    feature_access_mod = types.ModuleType(feature_access_name)
    feature_access_mod.get_feature_status = lambda feature_name: {"effective_state": "needs_redownload"}
    feature_access_mod.is_feature_ready_for_native_sync = lambda feature_name: ready_for_sync

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.services"] = services_pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[f"{package_name}.orbisauth"] = orbisauth_pkg
    sys.modules[jwt_name] = jwt_mod
    sys.modules[manager_name] = manager_mod
    sys.modules[feature_access_name] = feature_access_mod

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    apply_calls = []
    clear_calls = []
    native_status = dict(initial_native_status or {"authorized": False, "reason": ""})

    def get_license_status():
        return dict(native_status)

    def apply_grant(grant_token, jwks_json, addon_root):
        if verify_error is not None:
            raise verify_error
        apply_calls.append((grant_token, jwks_json, addon_root))

    def clear_license_state():
        clear_calls.append(True)

    return module, apply_calls, clear_calls, apply_grant, clear_license_state, get_license_status


class NativeFeatureSupportTest(unittest.TestCase):
    def test_sync_authorizes_feature_when_pre_native_state_is_ready(self):
        module, apply_calls, clear_calls, apply_grant, clear_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            apply_grant=apply_grant,
            clear_license_state=clear_license_state,
            get_license_status=get_license_status,
        )

        self.assertEqual(len(apply_calls), 1)
        self.assertEqual(apply_calls[-1][0], "grant-ok")
        self.assertEqual(clear_calls, [])

    def test_sync_marks_invalid_when_integrity_verification_fails(self):
        module, apply_calls, clear_calls, apply_grant, clear_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
            verify_error=RuntimeError("grant failed"),
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            apply_grant=apply_grant,
            clear_license_state=clear_license_state,
            get_license_status=get_license_status,
        )

        self.assertEqual(apply_calls, [])
        self.assertEqual(len(clear_calls), 1)

    def test_sync_does_not_reauthorize_after_native_integrity_failure(self):
        module, apply_calls, clear_calls, apply_grant, clear_license_state, get_license_status = load_support_module(
            ready_for_sync=True,
            initial_native_status={
                "authorized": False,
                "reason": "Face Capture integrity check failed: manager.py does not match the binary build.",
            },
        )

        module.sync_license_state_to_native(
            logger=types.SimpleNamespace(debug=lambda *args, **kwargs: None),
            feature_id="face_cap",
            apply_grant=apply_grant,
            clear_license_state=clear_license_state,
            get_license_status=get_license_status,
        )

        self.assertEqual(apply_calls, [])
        self.assertEqual(clear_calls, [])


if __name__ == "__main__":
    unittest.main()
