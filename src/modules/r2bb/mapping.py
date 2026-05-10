import json
import uuid
from functools import lru_cache
from pathlib import Path

import bpy

from ...services.errors import FeatureLockedError


ADDON_DIR = Path(__file__).resolve().parent
BUILTIN_PRESET_DIR = ADDON_DIR / "presets"

DEFAULT_PRESET_ID = "__default__"
MARCH_PRESET_ID = "__march__"
CURRENT_EDITOR_PRESET_ID = "__current__"
PRESET_SCHEMA_VERSION = 1
AXES = ("X", "Y", "Z")
_PRESET_ENUM_CACHE = {
    True: [],
    False: [],
}


def _default_axis_signs():
    return {axis: 1.0 for axis in AXES}


def _normalize_axis_signs(signs):
    normalized = _default_axis_signs()
    for axis in AXES:
        value = signs.get(axis, 1.0)
        normalized[axis] = -1.0 if float(value) < 0 else 1.0
    return normalized


def _normalize_mapping_entries_python(entries):
    normalized = []

    for raw_entry in entries or ():
        base_bone = str(raw_entry.get("base_bone", "") or "").strip()
        mi_bone = str(raw_entry.get("mi_bone", "") or "").strip()
        export_name = str(raw_entry.get("export_name", "") or "").strip()
        if not any((base_bone, mi_bone, export_name)):
            continue

        normalized.append({
            "base_bone": base_bone,
            "mi_bone": mi_bone,
            "export_name": export_name,
            "rotation_axis_signs": _normalize_axis_signs(raw_entry.get("rotation_axis_signs", {})),
            "transform_axis_signs": _normalize_axis_signs(raw_entry.get("transform_axis_signs", {})),
        })

    return normalized


def _get_r2bb_service_if_unlocked():
    from ...services.r2bb_service import get_r2bb_backend_service

    service = get_r2bb_backend_service()
    if service.is_feature_unlocked():
        return service

    status = service.get_feature_status()
    raise FeatureLockedError("R2BB", status.get("message", service.get_lock_reason()))


def normalize_mapping_entries(entries):
    return _get_r2bb_service_if_unlocked().normalize_mapping_entries(entries)


def _fallback_builtin_preset():
    return {
        "id": DEFAULT_PRESET_ID,
        "name": "Default (Built-in)",
        "description": "Fallback built-in preset",
        "builtin": True,
        "entries": tuple(),
    }


def _load_builtin_preset_file(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    preset_id = str(payload.get("id") or path.stem).strip()
    if not preset_id:
        return None

    preset_name = str(payload.get("name") or path.stem).strip() or path.stem
    description = str(payload.get("description") or "").strip()
    entries = tuple(_normalize_mapping_entries_python(payload.get("entries", [])))

    return {
        "id": preset_id,
        "name": preset_name,
        "description": description,
        "builtin": True,
        "entries": entries,
    }


@lru_cache(maxsize=1)
def load_builtin_presets():
    presets = []

    for path in sorted(BUILTIN_PRESET_DIR.glob("*.json"), key=lambda item: item.name.lower()):
        preset = _load_builtin_preset_file(path)
        if preset is not None:
            presets.append(preset)

    if not presets:
        presets.append(_fallback_builtin_preset())

    if not any(preset["id"] == DEFAULT_PRESET_ID for preset in presets):
        first = dict(presets[0])
        first["id"] = DEFAULT_PRESET_ID
        first["name"] = "Default (Built-in)"
        presets.insert(0, first)

    return tuple(presets)


def _builtin_preset_by_id(preset_id):
    target_id = preset_id or DEFAULT_PRESET_ID
    for preset in load_builtin_presets():
        if preset["id"] == target_id:
            return preset
    if target_id == DEFAULT_PRESET_ID:
        return load_builtin_presets()[0]
    return None


def _builtin_preset_ids():
    return {preset["id"] for preset in load_builtin_presets()}


def _preset_storage_dir():
    directory = bpy.utils.user_resource("CONFIG", path="rig2_r2bb_presets", create=True)
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        return path

    fallback = ADDON_DIR / "_user_presets"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _preset_file_for_id(preset_id):
    if not preset_id or preset_id in _builtin_preset_ids() or preset_id == CURRENT_EDITOR_PRESET_ID:
        return None
    return _preset_storage_dir() / f"{preset_id}.json"


def list_custom_presets():
    presets = []
    builtin_ids = _builtin_preset_ids()

    for path in sorted(_preset_storage_dir().glob("*.json"), key=lambda item: item.name.lower()):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        preset_id = str(payload.get("id") or path.stem).strip()
        if not preset_id or preset_id in builtin_ids or preset_id == CURRENT_EDITOR_PRESET_ID:
            continue

        preset_name = str(payload.get("name") or path.stem).strip() or path.stem
        presets.append({
            "id": preset_id,
            "name": preset_name,
            "path": path,
        })

    return presets


def get_preset_enum_items(include_current=False):
    items = []

    if include_current:
        items.append((
            CURRENT_EDITOR_PRESET_ID,
            "Current Editor",
            "Use the mappings currently shown in the R2BB mapping editor",
        ))

    for preset in load_builtin_presets():
        description = preset.get("description") or f"Use bundled preset: {preset['name']}"
        items.append((preset["id"], preset["name"], description))

    for preset in list_custom_presets():
        items.append((
            preset["id"],
            preset["name"],
            f"Saved custom preset: {preset['name']}",
        ))

    _PRESET_ENUM_CACHE[include_current] = items
    return _PRESET_ENUM_CACHE[include_current]


def load_preset_definition(preset_id):
    builtin = _builtin_preset_by_id(preset_id)
    if builtin is not None:
        return {
            "id": builtin["id"],
            "name": builtin["name"],
            "builtin": True,
            "entries": list(builtin["entries"]),
        }

    path = _preset_file_for_id(preset_id)
    if path is None or not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return {
        "id": str(payload.get("id") or preset_id),
        "name": str(payload.get("name") or path.stem).strip() or path.stem,
        "builtin": False,
        "entries": normalize_mapping_entries(payload.get("entries", [])),
    }


def save_custom_preset(name, entries, preset_id=None):
    normalized_entries = normalize_mapping_entries(entries)
    if not normalized_entries:
        raise ValueError("Cannot save an empty mapping preset")

    existing = load_preset_definition(preset_id) if preset_id else None
    if existing and existing.get("builtin"):
        existing = None

    resolved_id = existing["id"] if existing else uuid.uuid4().hex
    resolved_name = str(name or "").strip()
    if not resolved_name:
        resolved_name = existing["name"] if existing else "Custom Mapping"

    payload = {
        "schema_version": PRESET_SCHEMA_VERSION,
        "id": resolved_id,
        "name": resolved_name,
        "entries": normalized_entries,
    }

    path = _preset_file_for_id(resolved_id)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "id": resolved_id,
        "name": resolved_name,
        "builtin": False,
        "entries": normalized_entries,
    }


def delete_custom_preset(preset_id):
    path = _preset_file_for_id(preset_id)
    if path is None or not path.exists():
        return False

    path.unlink()
    return True


def mapping_entries_to_pairs(entries):
    normalized = normalize_mapping_entries(entries)
    return tuple(tuple(item) for item in _get_r2bb_service_if_unlocked().mapping_entries_to_pairs(normalized))


def mapping_entries_to_export_bones(entries):
    normalized = normalize_mapping_entries(entries)
    return tuple(_get_r2bb_service_if_unlocked().mapping_entries_to_export_bones(normalized))


def mapping_entries_to_export_name_map(entries):
    normalized = normalize_mapping_entries(entries)
    return dict(_get_r2bb_service_if_unlocked().mapping_entries_to_export_name_map(normalized))


def mapping_entries_to_rotation_axis_signs(entries):
    normalized = normalize_mapping_entries(entries)
    return dict(_get_r2bb_service_if_unlocked().mapping_entries_to_rotation_axis_signs(normalized))


def mapping_entries_to_transform_axis_signs(entries):
    normalized = normalize_mapping_entries(entries)
    return dict(_get_r2bb_service_if_unlocked().mapping_entries_to_transform_axis_signs(normalized))
