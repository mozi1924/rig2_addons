from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    label: str
    product_feature_name: str
    native_module_name: str
    native_api_version_attr: str
    expected_native_api_version: int
    required_callables: tuple[str, ...]
    required_attributes: tuple[str, ...]
    shared_secret: bytes
    integrity_targets: tuple[tuple[str, str], ...]
    download_module_name: str
    service_kind: str
    service_getter: str
    public_api_exposed: bool = True


FACE_CAP = "face_cap"
MIFRAMES = "miframes"

# Keep compatibility exports; registry is the primary source of truth.
FEATURE_FACE_CAP = FACE_CAP
FEATURE_MIFRAMES = MIFRAMES


_FEATURE_SPECS = {
    FACE_CAP: FeatureSpec(
        feature_id=FACE_CAP,
        label="Face Capture",
        product_feature_name=FACE_CAP,
        native_module_name="rig2_face_cap",
        native_api_version_attr="RIG2_FACE_CAP_API_VERSION",
        expected_native_api_version=3,
        required_callables=(
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
            "set_license_state",
            "verify_integrity",
        ),
        required_attributes=(
            "RIG2_FACE_CAP_API_VERSION",
            "BINARY_SUBPROTOCOL",
            "JSON_SUBPROTOCOL",
            "WEBSOCKET_MAGIC",
        ),
        shared_secret=bytes.fromhex(
            "a3f7b2c9d1e458076f3219ac4b6d0e87"
            "15c2f93a8b4e7612d5a098c3f7e1b649"
        ),
        integrity_targets=(
            ("face_cap_service.py", "services/face_cap_service.py"),
            ("manager.py", "licensing/manager.py"),
        ),
        download_module_name="rig2_face_cap",
        service_kind="face_cap",
        service_getter="rig2_addons.src.services.face_cap_service:get_face_cap_backend_service",
    ),
    MIFRAMES: FeatureSpec(
        feature_id=MIFRAMES,
        label="MIFrames",
        product_feature_name=MIFRAMES,
        native_module_name="rig2_miframes",
        native_api_version_attr="RIG2_MIFRAMES_API_VERSION",
        expected_native_api_version=2,
        required_callables=(
            "backend_name",
            "get_models",
            "get_model_config",
            "plan_miframes_keyframe_ops",
            "set_license_state",
            "verify_integrity",
        ),
        required_attributes=("RIG2_MIFRAMES_API_VERSION",),
        shared_secret=bytes.fromhex(
            "c8473d91e05a2f6b78d1c39e4a0b5726"
            "f9318c4d2e7a5b06f1d3c8e9a4b7f205"
        ),
        integrity_targets=(
            ("miframes_service.py", "services/miframes_service.py"),
            ("manager.py", "licensing/manager.py"),
        ),
        download_module_name="rig2_miframes",
        service_kind="miframes",
        service_getter="rig2_addons.src.services.miframes_service:get_miframes_backend_service",
    ),
}


def get_feature_spec(feature_id: str) -> FeatureSpec:
    return _FEATURE_SPECS[feature_id]


def iter_feature_specs() -> tuple[FeatureSpec, ...]:
    return tuple(_FEATURE_SPECS.values())


def iter_public_api_feature_specs() -> tuple[FeatureSpec, ...]:
    return tuple(spec for spec in _FEATURE_SPECS.values() if spec.public_api_exposed)
