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
    legacy_dir = os.path.join(native_root, "darwin-abi3")

    def build_native_module_path(module_name):
        active_suffixes = suffixes or [".abi3.so"]
        return [
            os.path.join(base_dir, module_name + suffix)
            for base_dir in (abi3_dir, legacy_dir)
            for suffix in active_suffixes
        ]

    loader_mod.get_arch_tag = lambda: arch_tag
    loader_mod.get_native_root = lambda: native_root
    loader_mod.get_abi3_platform_tag = lambda: "darwin-arm64-abi3"
    loader_mod.build_native_module_path = build_native_module_path
    loader_mod.get_preferred_extension_suffix = lambda: ".abi3.so"
    loader_mod.PlatformTarget = type(
        "PlatformTarget",
        (),
        {
            "current": staticmethod(
                lambda: types.SimpleNamespace(
                    platform_name="mac",
                    arch_name="arm64",
                    artifact_name="mac.dylib",
                    abi3_tag="darwin-arm64-abi3",
                )
            )
        },
    )

    def list_existing_native_module_paths(module_name):
        matches = []
        for base_dir in (abi3_dir, legacy_dir):
            if not os.path.isdir(base_dir):
                continue
            for entry in os.listdir(base_dir):
                if entry.startswith(module_name):
                    matches.append(os.path.join(base_dir, entry))
        return tuple(sorted(matches))

    loader_mod.list_existing_native_module_paths = list_existing_native_module_paths

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
                "rig2_face_cap.abi3.so",
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

    def test_ensure_native_binary_removes_residual_variants_before_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeManager(
                responses=[
                    types.SimpleNamespace(download_url="https://example.invalid/file"),
                ]
            )
            downloader = load_downloader_module(manager=manager, native_root=temp_dir)
            os.makedirs(os.path.join(temp_dir, "darwin-arm64-abi3"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "darwin-abi3"), exist_ok=True)
            with open(os.path.join(temp_dir, "darwin-abi3", "rig2_face_cap.cpython-311-darwin.so"), "wb") as handle:
                handle.write(b"old")

            ok = downloader.ensure_native_binary("rig2_face_cap", force=True)

            self.assertTrue(ok)
            self.assertFalse(
                os.path.exists(os.path.join(temp_dir, "darwin-abi3", "rig2_face_cap.cpython-311-darwin.so"))
            )


if __name__ == "__main__":
    unittest.main()
