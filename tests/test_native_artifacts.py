import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "native_artifacts.py"
SPEC = importlib.util.spec_from_file_location("rig2_test_native_artifacts", MODULE_PATH)
native_artifacts = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = native_artifacts
SPEC.loader.exec_module(native_artifacts)


class NativeArtifactsTest(unittest.TestCase):
    def test_validate_runtime_layout_requires_all_three_modules_per_tag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tag_dir = root / "darwin-arm64-abi3"
            tag_dir.mkdir(parents=True, exist_ok=True)
            (tag_dir / "rig2_face_cap.abi3.so").write_bytes(b"fc")
            (tag_dir / "rig2_miframes.abi3.so").write_bytes(b"mi")

            errors = native_artifacts.validate_runtime_layout(root)

            self.assertIn("missing module for darwin-arm64-abi3: rig2_r2bb", errors)

    def test_validate_runtime_layout_rejects_version_specific_binaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for module_name in native_artifacts.MODULE_NAMES:
                tag_dir = root / "linux-x86_64-abi3"
                tag_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{module_name}.cpython-311-x86_64-linux-gnu.so"
                (tag_dir / filename).write_bytes(b"x")

            errors = native_artifacts.validate_runtime_layout(root)

            self.assertTrue(any("version-specific filename" in error for error in errors))

    def test_map_wheel_platform_tag_to_runtime_tags_includes_r2bb_supported_targets(self):
        self.assertEqual(
            native_artifacts.map_wheel_platform_tag_to_runtime_tags("macosx_11_0_universal2"),
            ["darwin-x86_64-abi3", "darwin-arm64-abi3"],
        )
        self.assertEqual(
            native_artifacts.map_wheel_platform_tag_to_runtime_tags("manylinux_2_28_aarch64"),
            ["linux-arm64-abi3"],
        )


if __name__ == "__main__":
    unittest.main()
