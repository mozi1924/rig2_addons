import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADER_PATH = ROOT / "src" / "native" / "downloader.py"


def load_downloader_module(*, manager, native_root, arch_tag="arm64", suffixes=None):
    package_name = "rig2testpkg"
    downloader_name = f"{package_name}.native.downloader"
    loader_name = f"{package_name}.native.loader"
    manager_name = f"{package_name}.licensing.manager"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    native_pkg = types.ModuleType(f"{package_name}.native")
    native_pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []

    loader_mod = types.ModuleType(loader_name)
    abi3_dir = os.path.join(native_root, "darwin-arm64-abi3")

    def build_native_module_path(module_name):
        active_suffixes = suffixes or [".abi3.so"]
        return [os.path.join(abi3_dir, module_name + suffix) for suffix in active_suffixes]

    loader_mod.get_arch_tag = lambda: arch_tag
    loader_mod.get_native_root = lambda: native_root
    loader_mod.get_abi3_platform_tag = lambda: "darwin-arm64-abi3"
    loader_mod.build_native_module_path = build_native_module_path

    manager_mod = types.ModuleType(manager_name)
    manager_mod.get_license_manager = lambda: manager

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.native"] = native_pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[loader_name] = loader_mod
    sys.modules[manager_name] = manager_mod

    spec = importlib.util.spec_from_file_location(downloader_name, DOWNLOADER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[downloader_name] = module
    spec.loader.exec_module(module)
    return module


class FakeManager:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def is_activated(self):
        return True

    def request_download(self, **kwargs):
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def download_file(self, download_info, dest_path, progress_callback=None):
        with open(dest_path, "wb") as handle:
            handle.write(b"native-binary")


class NativeDownloaderTest(unittest.TestCase):
    def test_ensure_native_binary_falls_back_to_runtime_tag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager(
                responses=[
                    RuntimeError("explicit tuple request failed"),
                    types.SimpleNamespace(download_url="https://example.invalid/file"),
                ]
            )
            downloader = load_downloader_module(manager=manager, native_root=temp_dir)

            ok = downloader.ensure_native_binary("rig2_face_cap")

            self.assertTrue(ok)
            dest_path = os.path.join(
                temp_dir,
                "darwin-arm64-abi3",
                "rig2_face_cap" + importlib.machinery.EXTENSION_SUFFIXES[0],
            )
            self.assertTrue(os.path.exists(dest_path))
            self.assertEqual(
                manager.calls,
                [
                    {
                        "module": "rig2_face_cap",
                        "platform_tag": "mac",
                        "arch": "arm64",
                        "artifact": "",
                    },
                    {
                        "module": "rig2_face_cap",
                        "platform_tag": "mac",
                        "arch": "arm64",
                        "artifact": "mac.dylib",
                    },
                ],
            )

    def test_ensure_native_binary_raises_last_request_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager(
                responses=[
                    RuntimeError("platform request failed"),
                    RuntimeError("tuple request failed"),
                    ValueError("runtime-tag request failed"),
                ]
            )
            downloader = load_downloader_module(manager=manager, native_root=temp_dir)

            with self.assertRaisesRegex(ValueError, "runtime-tag request failed"):
                downloader.ensure_native_binary("rig2_miframes")


if __name__ == "__main__":
    unittest.main()
