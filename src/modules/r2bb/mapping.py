import json
import re
import uuid
from functools import lru_cache
from pathlib import Path

import bpy

from ...services.errors import FeatureLockedError


ADDON_DIR = Path(__file__).resolve().parent
MAPPING_FILE = ADDON_DIR / "mapping.txt"
ROTATION_AXES_FILE = ADDON_DIR / "ro_axes.txt"
TRANSFORM_AXES_FILE = ADDON_DIR / "tr_axes.txt"
MARCH_FILE = ADDON_DIR / "march.txt"

DEFAULT_PRESET_ID = "__default__"
CURRENT_EDITOR_PRESET_ID = "__current__"
PRESET_SCHEMA_VERSION = 1
AXES = ("X", "Y", "Z")
AXIS_TOKEN_RE = re.compile(r"([XYZ])(?:-C)?$")
_PRESET_ENUM_CACHE = {
    True: [],
    False: [],
}


def _default_axis_signs():
    return {axis: 1.0 for axis in AXES}


def _iter_mapping_lines(path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            yield line


def _load_txt_pairs(path):
    pairs = []

    for line in _iter_mapping_lines(path) or ():
        if "->" not in line:
            continue

        source_name, target_name = (part.strip() for part in line.split("->", 1))
        if source_name and target_name:
            pairs.append((source_name, target_name))

    return tuple(pairs)


def _load_axis_signs(path):
    axis_signs = {}

    for line in _iter_mapping_lines(path) or ():
        bone_name, separator, axis_spec = line.partition("(")
        if not separator or not axis_spec.endswith(")"):
            continue

        bone_name = bone_name.strip()
        if not bone_name:
            continue

        signs = _default_axis_signs()
        for token in axis_spec[:-1].split(","):
            token = token.strip().upper()
            if not token:
                continue

            match = AXIS_TOKEN_RE.fullmatch(token)
            if not match:
                continue

            axis = match.group(1)
            signs[axis] = -1.0 if token.endswith("-C") else 1.0

        axis_signs[bone_name] = signs

    return axis_signs


@lru_cache(maxsize=1)
def load_mapping_pairs():
    return _load_txt_pairs(MAPPING_FILE)


@lru_cache(maxsize=1)
def load_march_pairs():
    return _load_txt_pairs(MARCH_FILE)


@lru_cache(maxsize=1)
def load_rotation_axis_signs():
    return _load_axis_signs(ROTATION_AXES_FILE)


@lru_cache(maxsize=1)
def load_transform_axis_signs():
    return _load_axis_signs(TRANSFORM_AXES_FILE)


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


def _build_builtin_entries():
    mapping_pairs = load_mapping_pairs()
    march_pairs = dict(load_march_pairs())
    rotation_signs = load_rotation_axis_signs()
    transform_signs = load_transform_axis_signs()

    base_by_mi = {target_name: source_name for source_name, target_name in mapping_pairs}
    ordered_mi_names = []
    seen = set()

    def append_name(name):
        if name and name not in seen:
            seen.add(name)
            ordered_mi_names.append(name)

    for _, mi_name in mapping_pairs:
        append_name(mi_name)
    for mi_name, _ in load_march_pairs():
        append_name(mi_name)
    for mi_name in rotation_signs:
        append_name(mi_name)
    for mi_name in transform_signs:
        append_name(mi_name)

    entries = []
    for mi_name in ordered_mi_names:
        entries.append({
            "base_bone": base_by_mi.get(mi_name, ""),
            "mi_bone": mi_name,
            "export_name": march_pairs.get(mi_name, ""),
            "rotation_axis_signs": _normalize_axis_signs(rotation_signs.get(mi_name, {})),
            "transform_axis_signs": _normalize_axis_signs(transform_signs.get(mi_name, {})),
        })

    return tuple(_normalize_mapping_entries_python(entries))


@lru_cache(maxsize=1)
def load_builtin_preset_entries():
    return _build_builtin_entries()


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
    if not preset_id or preset_id in {DEFAULT_PRESET_ID, CURRENT_EDITOR_PRESET_ID}:
        return None
    return _preset_storage_dir() / f"{preset_id}.json"


def list_custom_presets():
    presets = []

    for path in sorted(_preset_storage_dir().glob("*.json"), key=lambda item: item.name.lower()):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        preset_id = str(payload.get("id") or path.stem)
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

    items.append((
        DEFAULT_PRESET_ID,
        "Default (Built-in)",
        "Use the bundled mapping/march/axis preset",
    ))

    for preset in list_custom_presets():
        items.append((
            preset["id"],
            preset["name"],
            f"Saved custom preset: {preset['name']}",
        ))

    _PRESET_ENUM_CACHE[include_current] = items
    return _PRESET_ENUM_CACHE[include_current]


def load_preset_definition(preset_id):
    if not preset_id or preset_id == DEFAULT_PRESET_ID:
        return {
            "id": DEFAULT_PRESET_ID,
            "name": "Default (Built-in)",
            "builtin": True,
            "entries": list(load_builtin_preset_entries()),
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
