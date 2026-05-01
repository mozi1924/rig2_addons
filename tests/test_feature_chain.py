import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = ROOT / "scripts" / "validate_feature_chain.py"
SPEC = importlib.util.spec_from_file_location("rig2_test_feature_chain", MODULE_PATH)
feature_chain = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = feature_chain
SPEC.loader.exec_module(feature_chain)


class FeatureChainTest(unittest.TestCase):
    def test_feature_chain_validator_passes(self):
        self.assertEqual(feature_chain.validate_feature_chain(), [])


if __name__ == "__main__":
    unittest.main()
