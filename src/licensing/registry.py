from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    """Native feature contract.

    Describes a Rig2 managed native feature and its module metadata.
    """
    feature_id: str
    label: str
    native_module_name: str
    native_source_filename: str
    native_api_version_attr: str
    expected_native_api_version: int
    required_callables: tuple[str, ...]
    required_attributes: tuple[str, ...]
    service_kind: str
    public_api_exposed: bool = True


FACE_CAP = "face_cap"
MIFRAMES = "miframes"
R2BB = "r2bb"

FEATURE_FACE_CAP = FACE_CAP
FEATURE_MIFRAMES = MIFRAMES
FEATURE_R2BB = R2BB


_FEATURE_SPECS = {
    FACE_CAP: FeatureSpec(
        feature_id=FACE_CAP,
        label="Face Capture",
        native_module_name="rig2_face_cap",
        native_source_filename="rig2_face_cap.cpp",
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
        ),
        required_attributes=(
            "RIG2_FACE_CAP_API_VERSION",
            "BINARY_SUBPROTOCOL",
            "JSON_SUBPROTOCOL",
            "WEBSOCKET_MAGIC",
        ),
        service_kind="face_cap",
    ),
    MIFRAMES: FeatureSpec(
        feature_id=MIFRAMES,
        label="MIFrames",
        native_module_name="rig2_miframes",
        native_source_filename="rig2_miframes.cpp",
        native_api_version_attr="RIG2_MIFRAMES_API_VERSION",
        expected_native_api_version=2,
        required_callables=(
            "backend_name",
            "get_models",
            "get_model_config",
            "plan_miframes_keyframe_ops",
        ),
        required_attributes=("RIG2_MIFRAMES_API_VERSION",),
        service_kind="miframes",
    ),
    R2BB: FeatureSpec(
        feature_id=R2BB,
        label="R2BB",
        native_module_name="rig2_r2bb",
        native_source_filename="rig2_r2bb.cpp",
        native_api_version_attr="RIG2_R2BB_API_VERSION",
        expected_native_api_version=1,
        required_callables=(
            "backend_name",
            "normalize_mapping_entries",
            "mapping_entries_to_pairs",
            "mapping_entries_to_export_bones",
            "mapping_entries_to_export_name_map",
            "mapping_entries_to_rotation_axis_signs",
            "mapping_entries_to_transform_axis_signs",
        ),
        required_attributes=("RIG2_R2BB_API_VERSION",),
        service_kind="r2bb",
    ),
}


def get_feature_spec(feature_id: str) -> FeatureSpec:
    return _FEATURE_SPECS[feature_id]


def iter_feature_specs() -> tuple[FeatureSpec, ...]:
    return tuple(_FEATURE_SPECS.values())


def iter_native_feature_specs() -> tuple[FeatureSpec, ...]:
    return tuple(spec for spec in _FEATURE_SPECS.values() if spec.native_module_name)


def iter_native_module_names() -> tuple[str, ...]:
    return tuple(spec.native_module_name for spec in iter_native_feature_specs())


def iter_public_api_feature_specs() -> tuple[FeatureSpec, ...]:
    return tuple(spec for spec in _FEATURE_SPECS.values() if spec.public_api_exposed)
