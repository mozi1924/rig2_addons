from __future__ import annotations

import importlib

from ..licensing.registry import get_feature_spec


def _resolve_addon_root_package() -> str:
    module_name = __name__
    marker = ".src."
    if marker in module_name:
        return module_name.split(marker, 1)[0]
    if module_name.endswith(".src"):
        return module_name[: -len(".src")]
    return "rig2_addons"


def _resolve_module_name(module_name: str) -> str:
    if module_name.startswith("rig2_addons."):
        addon_root = _resolve_addon_root_package()
        return module_name.replace("rig2_addons", addon_root, 1)
    return module_name


def get_feature_service(feature_id: str):
    spec = get_feature_spec(feature_id)
    module_name, attr_name = spec.service_getter.split(":", 1)
    module = importlib.import_module(_resolve_module_name(module_name))
    getter = getattr(module, attr_name)
    return getter()
