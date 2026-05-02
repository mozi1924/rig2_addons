import importlib.machinery
import importlib.util
import base64
import hashlib
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
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
        "r2bb_service.py": os.path.join(ROOT, "src", "services", "r2bb_service.py"),
        "mapping.py": os.path.join(ROOT, "src", "modules", "r2bb", "mapping.py"),
        "manager.py": os.path.join(ROOT, "src", "licensing", "manager.py"),
    }
    result = {}
    for name, path in watched.items():
        with open(path, "rb") as handle:
            result[name] = hashlib.sha256(handle.read()).hexdigest()
    return result


def unlock_native_module(native, feature_name: str):
    registry = load_registry_module()
    spec = registry.get_feature_spec(feature_name)
    payload = build_native_grant_payload(
        feature_name=feature_name,
        module_name=spec.native_module_name,
        module_path=native.__file__,
        integrity_targets=spec.integrity_targets,
    )
    token = sign_native_grant(payload)
    native.apply_native_grant(token, build_trust_bundle_token(), SRC, native.__file__)


TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC4pu+xJtmiIRMu
ha5XUInzKoyhUjS3O9smsODhRZkOHwII1Mc+EHFZQETjeBZxa36tqSH6ZpEpK4Kv
CYRrNbNugeO7l8j6RSwuEiaLxO96cqQLyOogPmfgsnnoqbNRkgHCLhb9KL9fF+ok
hX9vlCJxHYgI3oWi837nrcsV611fF4N5X8GxRPyusawdFQifLnZVAfnQiB5W7ilQ
3J3j7Om4bK/8oy6r9YCA7nFljvnJ9e/cQwp3nJz1F5EmGXdMC7XGOGbss7u6E6vh
c4EzF6qJVTPYNW8Rtg4a+9uetKpH4EuXT/hGyy7FWkKu25mo3wJd2M90nhomSrgn
/I1NQe1pAgMBAAECggEAHaY3Hu0RN/5zQTPs57ntFKhfNri88d5rajMvlhch+Ymo
FCPvrtBewEkuETpN8ZNO9B06xqVj0fEEcGJTqrqk35h9U+Njktq65SuRQz3G2D9X
256SCBsNJ0rGgWyHoxA8i7dGhgreGQD9iIoOXtZckL4rAtrm1AtLdBxMsO3UgHk/
IIwPJcS6AfQcBxb2ppVIx+JC2d3AV4B2LMXofhUv6vjPamvT3hdwGQDxcfxTemQe
SmtqGr+sUixinopJkpwNxpLd0X8SaPuy93YWY8RB72Ec7MNkQnE8d4PdeqswUUc+
EiT0o2X4sWYdpSLTMzid8I9ZPzD6vs0Y31tQ4MKEawKBgQD4nlZDdNFzLnE2/Lrx
PqhSdPg4fxSZLZ/s1XeHRh2oO6v3yKuVoYLhgOjZH9QFdWB7PjKgDEY9Z3tqdV8V
C2yLIqqKJ6LX9XEHq+fZOD0XYOsckG1BTctfG+8XsgfKGhp82XeT0agkmf64M7z7
6vr1RxGq8y8ck1blH/2VxKtX5wKBgQC+ImmvwSOwMn6x/QZeAIassh6NpeJ63FbB
Ln2CsdSj5kI7i114KRB1wS3wVKw8v1d7PuYgTmrsjswHOIRf3vDKmpYJ+i3cmjW+
42MOvOFrBcun/HHgkAsAIkFp674i4HvEYo1u5cP0T3bDGLdrd+O05fZWkfZlz0Fn
Y2F/tSumLwKBgACOwlzGX03l1cUszfKKlHAS6RefWVl6m7g5RlpcUua0s48LuS7N
vPBqjJsoEh6tA7ljC1QGkwXCPKmhd8QhUW4CduV2b0wStd0xioSXNrPduMlInaYe
2YzuEBw6fv/6DQMorbb8KmdinQqmuw7JmSSBs01x3DIxNmmvJ691UHkTAoGBAKe5
C6nyolzH7mNsZLV/mU22QqWJc+QVgqIfNLCZ1o5OjJaiNe3Nq6t0oeWji9x6nd0m
ezJ8em36+ZhVDtDThW30N+7NNq+niUm+pJ9XlzIlhqXFV19VMZ8ImNOrFasGg6eV
mFX/cYCOqKEpqIOw2rm1MjzjvYvJ7FQbouJZGwwZAoGBAMBd5PEbOfQQvpSxBi8R
2xaE99wl+h1P8JzKzhCBygSzzGj0VuMlkX1oJhFH167W/uW2iLZkyGtwsNVD7gua
UpTVtT2q/O3vjxIQF+HnyICnq/qem65kxjLIdS9O7F8wzeUP81Dix83O15GCyp/7
dloCS5tDj+dop+q+cB0ptEUY
-----END PRIVATE KEY-----
"""

TRUST_BUNDLE_PRIVATE_KEY_PEM = (
    os.environ.get("ORBISAUTH_TRUST_BUNDLE_TEST_PRIVATE_KEY")
    or os.environ.get("JWT_PRIVATE_KEY")
    or ""
)
TRUST_BUNDLE_KID = os.environ.get("JWT_KID", "orbisauth-rs256-v1")

TEST_JWKS_JSON = json.dumps({
    "keys": [{
        "kty": "RSA",
        "n": "uKbvsSbZoiETLoWuV1CJ8yqMoVI0tzvbJrDg4UWZDh8CCNTHPhBxWUBE43gWcWt-rakh-maRKSuCrwmEazWzboHju5fI-kUsLhImi8TvenKkC8jqID5n4LJ56KmzUZIBwi4W_Si_XxfqJIV_b5QicR2ICN6FovN-563LFetdXxeDeV_BsUT8rrGsHRUIny52VQH50IgeVu4pUNyd4-zpuGyv_KMuq_WAgO5xZY75yfXv3EMKd5yc9ReRJhl3TAu1xjhm7LO7uhOr4XOBMxeqiVUz2DVvEbYOGvvbnrSqR-BLl0_4RssuxVpCrtuZqN8CXdjPdJ4aJkq4J_yNTUHtaQ",
        "e": "AQAB",
        "kid": "test-key-v1",
        "alg": "RS256",
        "use": "sig",
    }]
}, sort_keys=True)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_native_grant(payload: dict) -> str:
    return sign_jwt(payload, TEST_PRIVATE_KEY_PEM, "test-key-v1")


def sign_jwt(payload: dict, private_key_pem: str, kid: str) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".pem", delete=False) as key_file:
        key_file.write(private_key_pem)
        key_path = key_file.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    finally:
        os.remove(key_path)
    signature_b64 = _b64url_encode(proc.stdout)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def build_trust_bundle_token() -> str:
    if not TRUST_BUNDLE_PRIVATE_KEY_PEM.strip():
        raise unittest.SkipTest("trusted Orbisauth private key is required for trust-bundle native contract tests")
    now = int(time.time())
    return sign_jwt(
        {
            "typ": "trust_bundle",
            "keys": json.loads(TEST_JWKS_JSON)["keys"],
            "iss": "orbisauth-worker",
            "aud": "orbisauth-trust-bundle",
            "iat": now,
            "exp": now + 3600,
        },
        TRUST_BUNDLE_PRIVATE_KEY_PEM,
        TRUST_BUNDLE_KID,
    )


def build_native_grant_payload(*, feature_name: str, module_name: str, module_path: str, integrity_targets):
    expires_at = int(time.time()) + 3600
    py_files = []
    for _, relative_path in integrity_targets:
        full_path = os.path.join(SRC, relative_path)
        with open(full_path, "rb") as handle:
            py_files.append({
                "path": relative_path,
                "sha256": hashlib.sha256(handle.read()).hexdigest(),
            })
    with open(module_path, "rb") as handle:
        artifact_sha = hashlib.sha256(handle.read()).hexdigest()
    return {
        "typ": "native_grant",
        "sub": "abc123license",
        "product": "rig2",
        "tier": "rig2_pro",
        "device_id": "native-contract-test-device",
        "feature_id": feature_name,
        "addon_version": "1.1.0",
        "py_manifest_version": 1,
        "py_manifest_hash": hashlib.sha256(json.dumps({"files": py_files}, sort_keys=True).encode("utf-8")).hexdigest(),
        "py_manifest": {"files": py_files},
        "artifact_manifest_version": 1,
        "artifact_manifest_hash": hashlib.sha256(json.dumps({
            "module": module_name,
            "artifact_sha256": artifact_sha,
            "artifact_size": os.path.getsize(module_path),
            "artifact": "test",
            "artifact_key": f"rig2/{module_name}/test",
            "platform": "mac",
            "arch": "arm64",
        }, sort_keys=True).encode("utf-8")).hexdigest(),
        "artifact_manifest": {
            "module": module_name,
            "artifact": "test",
            "artifact_key": f"rig2/{module_name}/test",
            "artifact_sha256": artifact_sha,
            "artifact_size": os.path.getsize(module_path),
            "platform": "mac",
            "arch": "arm64",
        },
        "iss": "orbisauth-worker",
        "aud": "orbisauth-native-grant",
        "iat": int(time.time()),
        "exp": expires_at,
    }


class NativeContractTest(unittest.TestCase):
    def test_miframes_required_symbols(self):
        native = load_native_module("rig2_miframes")
        self.assertEqual(native.RIG2_MIFRAMES_API_VERSION, 2)

        required = (
            "backend_name",
            "get_models",
            "get_model_config",
            "plan_miframes_keyframe_ops",
            "apply_native_grant",
            "clear_license_state",
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
            "apply_native_grant",
            "clear_license_state",
            "get_license_status",
        )
        for name in required:
            self.assertTrue(callable(getattr(native, name, None)), name)

    def test_r2bb_required_symbols(self):
        native = load_native_module("rig2_r2bb")
        self.assertEqual(native.RIG2_R2BB_API_VERSION, 1)

        required = (
            "backend_name",
            "normalize_mapping_entries",
            "mapping_entries_to_pairs",
            "mapping_entries_to_export_bones",
            "mapping_entries_to_export_name_map",
            "mapping_entries_to_rotation_axis_signs",
            "mapping_entries_to_transform_axis_signs",
            "apply_native_grant",
            "clear_license_state",
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
        native.clear_license_state()
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

    def test_r2bb_mapping_smoke(self):
        native = load_native_module("rig2_r2bb")
        unlock_native_module(native, "r2bb")
        self.assertTrue(native.get_license_status()["authorized"])

        entries = [
            {
                "base_bone": " Head root ",
                "mi_bone": " MI_Head ",
                "export_name": " head ",
                "rotation_axis_signs": {"X": 2.0, "Y": -1.0},
                "transform_axis_signs": {"Z": -9.0},
            },
            {"base_bone": "", "mi_bone": "", "export_name": ""},
        ]
        normalized = native.normalize_mapping_entries(entries)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["base_bone"], "Head root")
        self.assertEqual(normalized[0]["rotation_axis_signs"]["Y"], -1.0)
        self.assertEqual(native.mapping_entries_to_pairs(entries), [("Head root", "MI_Head")])
        self.assertEqual(native.mapping_entries_to_export_bones(entries), ["MI_Head"])
        self.assertEqual(native.mapping_entries_to_export_name_map(entries), {"MI_Head": "head"})


if __name__ == "__main__":
    unittest.main()
