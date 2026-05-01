import importlib.machinery
import importlib.util
import hashlib
import hmac
import json
import os
import platform
import struct
import sys
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
REGISTRY_PATH = os.path.join(ROOT, "src", "licensing", "registry.py")
def arch_tag() -> str:
    machine = (platform.machine() or "").strip().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


NATIVE_BIN_CANDIDATES = (
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-{arch_tag()}-abi3"),
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-abi3"),
    os.path.join(
        SRC,
        "native",
        "binaries",
        f"{sys.platform}-{arch_tag()}-{sys.version_info.major}{sys.version_info.minor}",
    ),
    os.path.join(
        SRC,
        "native",
        "binaries",
        f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}",
    ),
)


def load_native_module(module_name: str):
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None) or [".so", ".pyd", ".dylib"]
    for base_dir in NATIVE_BIN_CANDIDATES:
        for suffix in suffixes:
            module_path = os.path.join(base_dir, module_name + suffix)
            if os.path.exists(module_path):
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise FileNotFoundError(f"Native module {module_name} not found under {NATIVE_BIN_CANDIDATES}")


def load_registry_module():
    spec = importlib.util.spec_from_file_location("rig2_native_registry_test", REGISTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compute_source_hashes():
    watched = {
        "face_cap_service.py": os.path.join(ROOT, "src", "services", "face_cap_service.py"),
        "miframes_service.py": os.path.join(ROOT, "src", "services", "miframes_service.py"),
        "manager.py": os.path.join(ROOT, "src", "licensing", "manager.py"),
    }
    result = {}
    for name, path in watched.items():
        with open(path, "rb") as handle:
            result[name] = hashlib.sha256(handle.read()).hexdigest()
    return result


def unlock_native_module(native, feature_name: str):
    registry = load_registry_module()
    source_hashes = compute_source_hashes()
    native.verify_integrity(source_hashes)
    secret = registry.get_feature_spec(feature_name).shared_secret
    device_id = "native-contract-test-device"
    expires_at = int(time.time()) + 3600
    msg = f"{device_id}:{expires_at}".encode("utf-8")
    proof = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    native.set_license_state(device_id, expires_at, proof)


class NativeContractTest(unittest.TestCase):
    def test_miframes_required_symbols(self):
        native = load_native_module("rig2_miframes")
        self.assertEqual(native.RIG2_MIFRAMES_API_VERSION, 2)

        required = (
            "backend_name",
            "get_models",
            "get_model_config",
            "plan_miframes_keyframe_ops",
            "get_license_status",
        )
        for name in required:
            self.assertTrue(callable(getattr(native, name, None)), name)

    def test_face_cap_required_symbols(self):
        native = load_native_module("rig2_face_cap")
        self.assertEqual(native.RIG2_FACE_CAP_API_VERSION, 3)
        self.assertEqual(native.BINARY_SUBPROTOCOL, "r2fmc.bin.v1")
        self.assertEqual(native.JSON_SUBPROTOCOL, "r2fmc.json.v1")
        self.assertEqual(native.WEBSOCKET_MAGIC, "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")

        required = (
            "backend_name",
            "clamp01",
            "discover_local_ipv4",
            "face_payloads_equal",
            "parse_binary_packet",
            "parse_packet_text",
            "parse_schema_message",
            "quaternions_close",
            "resolve_transport_encoding",
            "sanitize_head_quaternion",
            "sniff_packet_type",
            "load_offline_face_cap_payload",
            "start_receiver",
            "stop_receiver",
            "poll_latest_packet",
            "get_receiver_stats",
            "get_license_status",
        )
        for name in required:
            self.assertTrue(callable(getattr(native, name, None)), name)

    def test_miframes_planner_smoke(self):
        native = load_native_module("rig2_miframes")
        unlock_native_module(native, "miframes")
        self.assertTrue(native.get_license_status()["authorized"])

        data = {
            "keyframes": [
                {
                    "position": 5,
                    "part_name": "Head",
                    "values": {
                        "ROT_X": 10,
                        "ROT_Y": 20,
                        "ROT_Z": 30,
                        "TRANSITION": "bezier",
                    },
                }
            ]
        }
        config = native.get_model_config("steve")
        plan = native.plan_miframes_keyframe_ops(data, config, 1.0, 2.0)

        self.assertIn("operations", plan)
        self.assertIn("transitions", plan)
        self.assertEqual(len(plan["operations"]), 2)
        self.assertEqual(sorted(op["handler_kind"] for op in plan["operations"]), ["pos_scl", "rot"])

    def test_face_cap_parse_binary_smoke(self):
        native = load_native_module("rig2_face_cap")
        native.set_license_state("native-contract-test-device", 0, "invalid")
        self.assertFalse(native.get_license_status()["authorized"])

        schema = ["jawOpen", "eyeBlinkLeft"]
        header = bytearray(24)
        struct.pack_into("<I", header, 0, 0x5232464D)
        header[4] = 1
        header[5] = 1
        struct.pack_into("<I", header, 8, 456)
        struct.pack_into("<H", header, 20, 1)

        face_header = bytearray(8)
        struct.pack_into("<H", face_header, 2, 2)
        face_header[4] = 0

        payload = header + face_header + struct.pack("<f", 0.2) + struct.pack("<f", 0.9)
        parsed = native.parse_binary_packet(bytes(payload), schema)

        self.assertEqual(parsed["face_count"], 1)
        self.assertEqual(parsed["sent_at"], "456")
        self.assertAlmostEqual(parsed["faces"][0]["blendshapes"]["jawOpen"], 0.2, places=6)
        self.assertAlmostEqual(parsed["faces"][0]["blendshapes"]["eyeBlinkLeft"], 0.9, places=6)

    def test_face_cap_offline_fixture_smoke(self):
        native = load_native_module("rig2_face_cap")
        unlock_native_module(native, "face_cap")
        self.assertTrue(native.get_license_status()["authorized"])
        fixture = os.path.join(ROOT, "tests", "fixtures", "face_cap", "offline_sample.json")
        result = native.load_offline_face_cap_payload(fixture)

        self.assertEqual(result["schema_names"], ["jawOpen", "eyeBlinkLeft"])
        self.assertGreater(len(result["frames"]), 0)
        self.assertGreater(result["video_fps"], 0.0)


if __name__ == "__main__":
    unittest.main()
