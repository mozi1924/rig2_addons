import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = ROOT / "scripts" / "validate_orbisauth_sdk.py"
SPEC = importlib.util.spec_from_file_location("rig2_test_orbisauth_sdk", MODULE_PATH)
validate_orbisauth_sdk = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = validate_orbisauth_sdk
SPEC.loader.exec_module(validate_orbisauth_sdk)


class OrbisAuthSdkContractTest(unittest.TestCase):
    def test_vendored_sdk_contract_validator_passes(self):
        self.assertEqual(validate_orbisauth_sdk.validate_orbisauth_sdk_contract(), [])


if __name__ == "__main__":
    unittest.main()
