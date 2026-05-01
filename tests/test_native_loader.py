import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER_PATH = ROOT / "src" / "native" / "loader.py"


def load_loader_module(native_root):
    package_name = "rig2testpkg_loader"
    loader_name = f"{package_name}.native.loader"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    native_pkg = types.ModuleType(f"{package_name}.native")
    native_pkg.__path__ = []

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.native"] = native_pkg

    os.environ["RIG2_NATIVE_ROOT"] = native_root
    spec = importlib.util.spec_from_file_location(loader_name, LOADER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[loader_name] = module
    spec.loader.exec_module(module)
    return module


class NativeLoaderTest(unittest.TestCase):
    def test_missing_binary_does_not_attempt_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            loader = load_loader_module(temp_dir)
            result = loader.load_native_extension_result("rig2_face_cap")

            self.assertFalse(result.is_available)
            self.assertIn("missing binary", result.error)

    def test_preferred_suffix_prefers_abi3(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            loader = load_loader_module(temp_dir)
            self.assertIn(".abi3.", loader.get_preferred_extension_suffix())


if __name__ == "__main__":
    unittest.main()
