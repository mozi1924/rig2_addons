import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


script_versioning = load_module("rig2_script_versioning_test", ROOT / "scripts" / "versioning.py")
package_addon = load_module("rig2_package_addon_test", ROOT / "scripts" / "package_addon.py")
runtime_versioning = load_module("rig2_runtime_versioning_test", ROOT / "src" / "core" / "versioning.py")


class VersioningTest(unittest.TestCase):
    def test_version_json_matches_runtime_tuple(self):
        with (ROOT / "version.json").open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        self.assertEqual(
            runtime_versioning.get_version_tuple(),
            (payload["major"], payload["minor"], payload["patch"]),
        )

    def test_bump_patch_resets_nothing_else(self):
        bumped = script_versioning.bump_version({"major": 1, "minor": 2, "patch": 3}, "patch")
        self.assertEqual(bumped, {"major": 1, "minor": 2, "patch": 4})

    def test_bump_minor_resets_patch(self):
        bumped = script_versioning.bump_version({"major": 1, "minor": 2, "patch": 3}, "minor")
        self.assertEqual(bumped, {"major": 1, "minor": 3, "patch": 0})

    def test_packaging_injects_literal_blender_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            init_path = Path(temp_dir) / "__init__.py"
            init_path.write_text(
                'bl_info = {\n    "version": BL_INFO_VERSION,\n}\n',
                encoding="utf-8",
            )
            package_addon.inject_bl_info_version(init_path, (1, 2, 3))

            content = init_path.read_text(encoding="utf-8")
        self.assertIn('"version": (1, 2, 3),', content)
        self.assertNotIn("BL_INFO_VERSION", content)


if __name__ == "__main__":
    unittest.main()
