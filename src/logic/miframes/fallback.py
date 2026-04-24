"""
Python fallback entrypoints for miframes logic.

Later, these functions should become the compatibility surface shared by:
- pure Python implementations during refactor
- downloaded native extensions in release builds
"""

from .planner import plan_miframes_keyframe_ops
from .model_registry import get_models, get_model_config


def backend_name():
    return "python"


__all__ = [
    "backend_name",
    "get_models",
    "get_model_config",
    "plan_miframes_keyframe_ops",
]
