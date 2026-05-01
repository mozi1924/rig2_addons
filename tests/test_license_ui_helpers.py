import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_HELPERS_PATH = ROOT / "src" / "licensing" / "ui_helpers.py"
spec = importlib.util.spec_from_file_location("rig2_test_license_ui_helpers", UI_HELPERS_PATH)
ui_helpers = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(ui_helpers)


class LicenseUIHelpersTest(unittest.TestCase):
    def test_format_expiry_label_and_timestamp(self):
        self.assertEqual(ui_helpers.format_expiry_label(0), "Expired")
        self.assertEqual(ui_helpers.format_expiry_label(3661), "1h 1m remaining")
        self.assertEqual(ui_helpers.format_expiry_label(90061), "1d 1h 1m remaining")
        self.assertEqual(ui_helpers.format_timestamp_local(0), "Unknown")

    def test_format_heartbeat_label(self):
        self.assertEqual(
            ui_helpers.format_heartbeat_label({"heartbeat_in_flight": True}),
            "syncing...",
        )
        self.assertEqual(
            ui_helpers.format_heartbeat_label({"heartbeat_overdue_seconds": 125}),
            "overdue by 2m",
        )
        self.assertEqual(
            ui_helpers.format_heartbeat_label({"consecutive_heartbeat_failures": 4}),
            "4 failed attempts",
        )
        self.assertEqual(
            ui_helpers.format_heartbeat_label({"last_heartbeat_at": 10}),
            "healthy",
        )
        self.assertEqual(ui_helpers.format_heartbeat_label({}), "pending")


if __name__ == "__main__":
    unittest.main()
