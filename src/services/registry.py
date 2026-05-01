from __future__ import annotations

import importlib

from ..licensing.registry import get_feature_spec


def get_feature_service(feature_id: str):
    spec = get_feature_spec(feature_id)
    module_name, attr_name = spec.service_getter.split(":", 1)
    module = importlib.import_module(module_name)
    getter = getattr(module, attr_name)
    return getter()
