import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE_ACCESS_PATH = ROOT / "src" / "licensing" / "feature_access.py"


class WrapperState:
    def __init__(self, feature_name, temp_dir):
        self.feature_name = feature_name
        self.module_name = "rig2_face_cap" if feature_name == "face_cap" else "rig2_miframes"
        self.path = os.path.join(temp_dir, self.module_name + ".abi3.so")
        self.load_ok = False
        self.error = ""
        self.refresh_count = 0

    def refresh(self):
        self.refresh_count += 1

    def is_native_backend(self):
        return os.path.exists(self.path) and self.load_ok

    def get_load_state(self):
        return {
            "module_name": self.module_name,
            "module_path": self.path if os.path.exists(self.path) else "",
            "error": self.error,
            "is_available": self.is_native_backend(),
            "candidate_paths": (self.path,),
        }


class FakeManager:
    def __init__(self):
        self.status = {
            "activated": False,
            "product": "Rig2",
            "tier": "Pro",
            "license_id": "lic_test",
            "device_id": "dev_test",
            "warnings": [],
            "is_refresh_expired": False,
        }
        self._client = types.SimpleNamespace(session=None)
        self.activate_features = {}

    def get_status(self):
        return dict(self.status)

    def activate(self, license_key):
        session = types.SimpleNamespace(
            product="Rig2",
            tier="Pro",
            features=dict(self.activate_features),
        )
        self._client.session = session
        self.status["activated"] = True
        self.status["warnings"] = []
        self.status["is_refresh_expired"] = False
        return session


def load_feature_access_module(*, manager, temp_dir, downloader_behavior, runtime_service):
    package_name = "rig2testpkg_feature_access"
    module_name = f"{package_name}.licensing.feature_access"
    config_name = f"{package_name}.licensing.config"
    paths_name = f"{package_name}.licensing.paths"
    manager_name = f"{package_name}.licensing.manager"
    downloader_name = f"{package_name}.native.downloader"
    loader_name = f"{package_name}.native.loader"
    face_wrapper_name = f"{package_name}.native.face_cap_wrapper"
    miframes_wrapper_name = f"{package_name}.native.miframes_wrapper"
    runtime_name = f"{package_name}.modules.face_cap.runtime"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []
    native_pkg = types.ModuleType(f"{package_name}.native")
    native_pkg.__path__ = []
    modules_pkg = types.ModuleType(f"{package_name}.modules")
    modules_pkg.__path__ = []
    face_cap_pkg = types.ModuleType(f"{package_name}.modules.face_cap")
    face_cap_pkg.__path__ = []

    wrapper_states = {
        "face_cap": WrapperState("face_cap", temp_dir),
        "miframes": WrapperState("miframes", temp_dir),
    }

    config_mod = types.ModuleType(config_name)
    config_mod.FEATURE_FACE_CAP = "face_cap"
    config_mod.FEATURE_MIFRAMES = "miframes"

    paths_mod = types.ModuleType(paths_name)
    paths_mod.get_feature_status_path = lambda: os.path.join(temp_dir, "rig2_feature_status.json")

    manager_mod = types.ModuleType(manager_name)
    manager_mod.get_license_manager = lambda: manager

    def make_wrapper_module(state):
        module = types.ModuleType(
            face_wrapper_name if state.feature_name == "face_cap" else miframes_wrapper_name
        )
        module.refresh_native_backend = state.refresh
        module.is_native_backend = state.is_native_backend
        module.get_load_state = state.get_load_state
        return module

    downloader_mod = types.ModuleType(downloader_name)
    loader_mod = types.ModuleType(loader_name)

    def ensure_native_binary(module_name, force=False):
        return downloader_behavior(module_name, force, wrapper_states)

    downloader_mod.ensure_native_binary = ensure_native_binary
    loader_mod.get_primary_native_module_path = lambda module_name: os.path.join(
        temp_dir,
        module_name + ".abi3.so",
    )
    loader_mod.list_existing_native_module_paths = lambda module_name: tuple(
        sorted(
            state.path
            for state in wrapper_states.values()
            if state.module_name == module_name and os.path.exists(state.path)
        )
    )
    loader_mod.get_residual_native_module_paths = lambda module_name: ()

    runtime_mod = types.ModuleType(runtime_name)
    runtime_mod.get_runtime_service = lambda: runtime_service

    licensing_pkg.sync_license_to_native_modules = lambda: None

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[f"{package_name}.native"] = native_pkg
    sys.modules[f"{package_name}.modules"] = modules_pkg
    sys.modules[f"{package_name}.modules.face_cap"] = face_cap_pkg
    sys.modules[config_name] = config_mod
    sys.modules[paths_name] = paths_mod
    sys.modules[manager_name] = manager_mod
    sys.modules[downloader_name] = downloader_mod
    sys.modules[loader_name] = loader_mod
    sys.modules[face_wrapper_name] = make_wrapper_module(wrapper_states["face_cap"])
    sys.modules[miframes_wrapper_name] = make_wrapper_module(wrapper_states["miframes"])
    sys.modules[runtime_name] = runtime_mod

    spec = importlib.util.spec_from_file_location(module_name, FEATURE_ACCESS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, wrapper_states


class FakeRuntimeService:
    def __init__(self):
        self.refresh_count = 0

    def refresh_backend(self):
        self.refresh_count += 1


class FeatureAccessTest(unittest.TestCase):
    def test_unactivated_status_and_session_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager()
            runtime_service = FakeRuntimeService()

            def downloader_behavior(module_name, force, wrapper_states):
                return False

            feature_access, wrapper_states = load_feature_access_module(
                manager=manager,
                temp_dir=temp_dir,
                downloader_behavior=downloader_behavior,
                runtime_service=runtime_service,
            )

            status = feature_access.get_feature_status("face_cap")
            self.assertEqual(status["effective_state"], "unactivated")
            self.assertIn("Activate your license", status["message"])

            manager._client.session = types.SimpleNamespace(features={"face_cap": True})
            manager.status["warnings"] = [{"level": "WARNING", "message": "Connect to the internet"}]
            manager.status["activated"] = False
            with open(wrapper_states["face_cap"].path, "wb") as handle:
                handle.write(b"bin")
            wrapper_states["face_cap"].load_ok = True

            warning_status = feature_access.get_feature_status("face_cap")
            self.assertEqual(warning_status["effective_state"], "session_warning")
            self.assertTrue(feature_access.is_feature_ready("face_cap"))

    def test_binary_missing_download_failed_and_needs_redownload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager()
            manager._client.session = types.SimpleNamespace(features={"face_cap": True})
            manager.status["activated"] = True
            runtime_service = FakeRuntimeService()

            def downloader_behavior(module_name, force, wrapper_states):
                raise RuntimeError("network down")

            feature_access, wrapper_states = load_feature_access_module(
                manager=manager,
                temp_dir=temp_dir,
                downloader_behavior=downloader_behavior,
                runtime_service=runtime_service,
            )

            missing_status = feature_access.get_feature_status("face_cap")
            self.assertEqual(missing_status["effective_state"], "binary_missing")

            result = feature_access.download_feature_binary("face_cap")
            self.assertFalse(result["ok"])
            failed_status = feature_access.get_feature_status("face_cap")
            self.assertEqual(failed_status["effective_state"], "download_failed")
            self.assertIn("Retry from Addon Preferences", failed_status["message"])

            with open(wrapper_states["face_cap"].path, "wb") as handle:
                handle.write(b"bin")
            wrapper_states["face_cap"].load_ok = False
            wrapper_states["face_cap"].error = "validation failed"
            invalid_status = feature_access.get_feature_status("face_cap")
            self.assertEqual(invalid_status["effective_state"], "needs_redownload")
            self.assertEqual(invalid_status["load_error"], "validation failed")
            self.assertTrue(invalid_status["can_download"])
            self.assertTrue(invalid_status["can_retry"])

    def test_activate_and_prepare_features_allows_partial_download_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager()
            manager.activate_features = {
                "face_cap": True,
                "miframes": True,
            }
            runtime_service = FakeRuntimeService()

            def downloader_behavior(module_name, force, wrapper_states):
                if module_name == "rig2_face_cap":
                    with open(wrapper_states["face_cap"].path, "wb") as handle:
                        handle.write(b"bin")
                    wrapper_states["face_cap"].load_ok = True
                    return True
                raise RuntimeError("miframes unavailable")

            feature_access, wrapper_states = load_feature_access_module(
                manager=manager,
                temp_dir=temp_dir,
                downloader_behavior=downloader_behavior,
                runtime_service=runtime_service,
            )

            result = feature_access.activate_and_prepare_features("KEY-123")

            self.assertEqual(result["licensed_features"], ["face_cap", "miframes"])
            self.assertTrue(result["download_results"]["face_cap"]["ok"])
            self.assertFalse(result["download_results"]["miframes"]["ok"])
            self.assertEqual(feature_access.get_feature_status("face_cap")["effective_state"], "ready")
            self.assertEqual(
                feature_access.get_feature_status("miframes")["effective_state"],
                "download_failed",
            )
            self.assertGreaterEqual(runtime_service.refresh_count, 1)
            self.assertGreaterEqual(wrapper_states["face_cap"].refresh_count, 1)


if __name__ == "__main__":
    unittest.main()
