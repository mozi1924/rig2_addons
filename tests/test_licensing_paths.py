import os
import tempfile
import unittest
from unittest import mock
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATHS_PATH = ROOT / "src" / "licensing" / "paths.py"
spec = importlib.util.spec_from_file_location("rig2_test_licensing_paths", PATHS_PATH)
paths = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(paths)


class LicensingPathsTest(unittest.TestCase):
    def test_session_dir_prefers_explicit_override(self):
        with tempfile.TemporaryDirectory() as session_dir:
            with mock.patch.dict(os.environ, {"RIG2_SESSION_DIR": session_dir}, clear=False):
                result = paths.get_session_dir()
        self.assertEqual(result, os.path.normpath(session_dir))

    def test_session_dir_falls_back_to_native_root_when_user_state_unwritable(self):
        with tempfile.TemporaryDirectory() as native_root:
            with mock.patch.dict(
                os.environ,
                {
                    "RIG2_SESSION_DIR": "/definitely/not/writable",
                    "RIG2_NATIVE_ROOT": native_root,
                },
                clear=False,
            ):
                original_makedirs = os.makedirs

                def fake_makedirs(path, exist_ok=False):
                    normalized = os.path.normpath(path)
                    if normalized == os.path.normpath("/definitely/not/writable"):
                        raise OSError("no write access")
                    return original_makedirs(path, exist_ok=exist_ok)

                with mock.patch.object(paths.os, "makedirs", side_effect=fake_makedirs):
                    result = paths.get_session_dir()

        self.assertEqual(result, os.path.normpath(native_root))

    def test_session_dir_falls_back_to_temp_when_native_root_unwritable(self):
        with mock.patch.dict(
            os.environ,
            {
                "RIG2_SESSION_DIR": "/definitely/not/writable",
                "RIG2_NATIVE_ROOT": "/also/not/writable",
            },
            clear=False,
        ):
            original_makedirs = os.makedirs
            temp_root = tempfile.gettempdir()

            def fake_makedirs(path, exist_ok=False):
                normalized = os.path.normpath(path)
                if normalized in {
                    os.path.normpath("/definitely/not/writable"),
                    os.path.normpath("/also/not/writable"),
                }:
                    raise OSError("no write access")
                return original_makedirs(path, exist_ok=exist_ok)

            with mock.patch.object(paths.os, "makedirs", side_effect=fake_makedirs):
                result = paths.get_session_dir()

        self.assertEqual(result, os.path.join(temp_root, "rig2_addons"))


if __name__ == "__main__":
    unittest.main()
