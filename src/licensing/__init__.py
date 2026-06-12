"""Rig2 feature licensing — open source build, always active."""
from .registry import (
    FEATURE_FACE_CAP,
    FEATURE_MIFRAMES,
    FEATURE_R2BB,
    FACE_CAP,
    MIFRAMES,
    R2BB,
    FeatureSpec,
    get_feature_spec,
    iter_feature_specs,
)

__all__ = [
    "FEATURE_FACE_CAP",
    "FEATURE_MIFRAMES",
    "FEATURE_R2BB",
    "FACE_CAP",
    "MIFRAMES",
    "R2BB",
    "FeatureSpec",
    "get_feature_spec",
    "iter_feature_specs",
    "is_runtime_ready",
    "register",
    "unregister",
]

_LICENSE_RUNTIME_READY = True


def is_runtime_ready():
    return True


def register():
    pass


def unregister():
    pass
