from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from .licensing.feature_access import FeatureVisibility, get_feature_visibility

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureModuleSpec:
    feature_id: str
    module_path: str


_FEATURE_MODULE_SPECS = (
    FeatureModuleSpec(
        feature_id="face_cap",
        module_path="rig2_addons.src.modules.face_cap",
    ),
    FeatureModuleSpec(
        feature_id="miframes",
        module_path="rig2_addons.src.modules.rig_controls.miframes",
    ),
    FeatureModuleSpec(
        feature_id="r2bb",
        module_path="rig2_addons.src.modules.r2bb",
    ),
)

_ACTIVE_MODULES: dict[str, object] = {}
_COORDINATOR_REGISTERED = False


def _feature_module_specs():
    return _FEATURE_MODULE_SPECS


def _load_module(module_path: str):
    return importlib.import_module(module_path)


def _refresh_ui():
    try:
        import bpy

        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _should_register(spec: FeatureModuleSpec):
    try:
        visibility = get_feature_visibility(spec.feature_id)
    except Exception as exc:
        _log.debug("feature visibility %s unavailable: %s", spec.feature_id, exc)
        return False
    return visibility in (FeatureVisibility.DISABLED, FeatureVisibility.ENABLED)


def reconcile_feature_modules():
    if not _COORDINATOR_REGISTERED:
        return

    for spec in _feature_module_specs():
        is_active = spec.feature_id in _ACTIVE_MODULES
        should_register = _should_register(spec)
        if should_register and not is_active:
            try:
                module = _load_module(spec.module_path)
                if hasattr(module, "register"):
                    module.register()
                _ACTIVE_MODULES[spec.feature_id] = module
            except Exception as exc:
                _log.warning("Failed to register feature module %s: %s", spec.feature_id, exc)
        elif not should_register and is_active:
            module = _ACTIVE_MODULES.pop(spec.feature_id, None)
            if module is None:
                continue
            try:
                if hasattr(module, "unregister"):
                    module.unregister()
            except Exception as exc:
                _log.warning("Failed to unregister feature module %s: %s", spec.feature_id, exc)

    _refresh_ui()


def register():
    global _COORDINATOR_REGISTERED
    _COORDINATOR_REGISTERED = True
    reconcile_feature_modules()


def unregister():
    global _COORDINATOR_REGISTERED
    _COORDINATOR_REGISTERED = False
    for spec in reversed(_feature_module_specs()):
        module = _ACTIVE_MODULES.pop(spec.feature_id, None)
        if module is None:
            continue
        try:
            if hasattr(module, "unregister"):
                module.unregister()
        except Exception as exc:
            _log.warning("Failed to unregister feature module %s: %s", spec.feature_id, exc)

    _refresh_ui()
