import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "modules" / "face_cap" / "runtime.py"


def load_runtime_module():
    package_name = "rig2testpkg_face_cap_runtime"
    module_name = f"{package_name}.modules.face_cap.runtime"
    constants_name = f"{package_name}.core.constants"
    utils_name = f"{package_name}.core.utils"
    service_name = f"{package_name}.services.face_cap_service"
    props_name = f"{package_name}.modules.face_cap.props"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    modules_pkg = types.ModuleType(f"{package_name}.modules")
    modules_pkg.__path__ = []
    face_cap_pkg = types.ModuleType(f"{package_name}.modules.face_cap")
    face_cap_pkg.__path__ = []
    core_pkg = types.ModuleType(f"{package_name}.core")
    core_pkg.__path__ = []
    services_pkg = types.ModuleType(f"{package_name}.services")
    services_pkg.__path__ = []

    handlers = []
    bpy_mod = types.ModuleType("bpy")
    bpy_mod.context = types.SimpleNamespace(scene=None)
    bpy_mod.data = types.SimpleNamespace(scenes=[], objects={})
    bpy_mod.app = types.SimpleNamespace(
        handlers=types.SimpleNamespace(load_post=handlers, persistent=lambda fn: fn),
        timers=types.SimpleNamespace(register=lambda *args, **kwargs: None, unregister=lambda *args, **kwargs: None),
    )

    bpy_app_mod = types.ModuleType("bpy.app")
    bpy_app_handlers_mod = types.ModuleType("bpy.app.handlers")
    bpy_app_handlers_mod.persistent = lambda fn: fn

    constants_mod = types.ModuleType(constants_name)
    constants_mod.INTERNAL_KEYS = {"_RNA_UI", "is_rig2"}

    utils_mod = types.ModuleType(utils_name)
    utils_mod.is_rig2_armature = lambda obj: True
    utils_mod.refresh_rig_driver_batch = lambda *args, **kwargs: None

    props_mod = types.ModuleType(props_name)
    props_mod.get_face_cap_bindings = lambda scene: []
    props_mod.get_face_cap_settings = lambda scene: None

    service_state = {"service": None}
    service_mod = types.ModuleType(service_name)
    service_mod.get_face_cap_backend_service = lambda: service_state["service"]
    service_state["service"] = types.SimpleNamespace(
        get_runtime_bindings=lambda: {
            "start_receiver": None,
            "stop_receiver": lambda: None,
            "poll_latest_packet": None,
            "get_receiver_stats": None,
        },
        is_feature_unlocked=lambda: False,
        get_lock_reason=lambda: "locked",
    )

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.modules"] = modules_pkg
    sys.modules[f"{package_name}.modules.face_cap"] = face_cap_pkg
    sys.modules[f"{package_name}.core"] = core_pkg
    sys.modules[f"{package_name}.services"] = services_pkg
    sys.modules["bpy"] = bpy_mod
    sys.modules["bpy.app"] = bpy_app_mod
    sys.modules["bpy.app.handlers"] = bpy_app_handlers_mod
    sys.modules[constants_name] = constants_mod
    sys.modules[utils_name] = utils_mod
    sys.modules[props_name] = props_mod
    sys.modules[service_name] = service_mod

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, service_state


class FaceCapRuntimeTest(unittest.TestCase):
    def test_refresh_backend_stops_previous_receiver_when_feature_becomes_locked(self):
        module, service_state = load_runtime_module()
        stop_calls = []
        unlocked_bindings = {
            "start_receiver": lambda *args, **kwargs: None,
            "stop_receiver": lambda *args, **kwargs: stop_calls.append("stopped"),
            "poll_latest_packet": lambda: None,
            "get_receiver_stats": lambda: None,
        }
        locked_bindings = {
            "start_receiver": None,
            "stop_receiver": lambda: None,
            "poll_latest_packet": None,
            "get_receiver_stats": None,
        }
        service_state["service"] = types.SimpleNamespace(
            get_runtime_bindings=lambda: unlocked_bindings,
            is_feature_unlocked=lambda: True,
            get_lock_reason=lambda: "locked",
        )
        runtime = module.FaceCapRuntimeService()
        runtime._runtime_bindings = unlocked_bindings
        runtime._native_receiver_enabled = True
        runtime._native_is_listening = True
        runtime._native_host = "127.0.0.1"
        runtime._native_port = 9000

        service_state["service"] = types.SimpleNamespace(
            get_runtime_bindings=lambda: locked_bindings,
            is_feature_unlocked=lambda: False,
            get_lock_reason=lambda: "locked",
        )

        runtime.refresh_backend()

        self.assertEqual(stop_calls, ["stopped"])
        self.assertFalse(runtime._native_receiver_enabled)
        self.assertFalse(runtime._native_is_listening)
        self.assertEqual(runtime._native_port, 0)


if __name__ == "__main__":
    unittest.main()
