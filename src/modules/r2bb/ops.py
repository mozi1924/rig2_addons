import json
import re
from collections import defaultdict
from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper

from ...core.utils import is_rig2_armature
from ...i18n import format_text as _f
from ...i18n import iface as _
from .export_json import (
    EXPORT_FORMAT_ITEMS,
    default_export_filepath,
    ensure_animation_json_suffix,
    export_geckolib_json,
    get_export_animation_name,
)
from .mapping import (
    CURRENT_EDITOR_PRESET_ID,
    DEFAULT_PRESET_ID,
    delete_custom_preset,
    get_preset_enum_items,
    load_preset_definition,
    mapping_entries_to_export_bones,
    mapping_entries_to_pairs,
    normalize_mapping_entries,
    save_custom_preset,
)
from .props import editor_entries_to_runtime, ensure_editor_initialized, set_editor_entries
from .shared import BONE_DATA_PATH_RE, get_action, get_keyed_frames


def _ensure_r2bb_access(operator):
    from ...services.r2bb_service import get_r2bb_backend_service

    service = get_r2bb_backend_service()
    if service.is_feature_unlocked():
        return True

    operator.report({"ERROR"}, service.get_lock_reason())
    return False


def _export_preset_items(self, context):
    return get_preset_enum_items(include_current=True)


def _ensure_plain_json_suffix(filepath):
    cleaned = str(filepath or "").strip()
    if not cleaned:
        return cleaned
    if cleaned.lower().endswith(".json"):
        return cleaned
    return f"{cleaned}.json"


def _safe_mapping_filename(name):
    token = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(name or "").strip()).strip("._-")
    if not token:
        token = "r2bb_mapping"
    return f"{token}.json"


def _extract_import_mapping_payload(payload, fallback_name):
    if isinstance(payload, list):
        entries = payload
        name = fallback_name
        return name, entries

    if not isinstance(payload, dict):
        raise ValueError(_("JSON root must be an object or an array"))

    entries = payload.get("entries")
    if not isinstance(entries, list):
        for key in ("mapping", "mappings"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                entries = candidate
                break

    if not isinstance(entries, list):
        raise ValueError(_("JSON must include an 'entries' array"))

    name = str(payload.get("name") or fallback_name).strip() or fallback_name
    return name, entries


def _get_bone_depth(pose_bone):
    depth = 0
    bone = pose_bone
    while bone.parent:
        depth += 1
        bone = bone.parent
    return depth


def _resolve_mapping_entries(context, preset_id=CURRENT_EDITOR_PRESET_ID):
    state = ensure_editor_initialized(context.scene)
    if state is None:
        preset = load_preset_definition(DEFAULT_PRESET_ID)
        return preset["entries"] if preset else []

    if not preset_id or preset_id == CURRENT_EDITOR_PRESET_ID:
        return editor_entries_to_runtime(state.entries)

    preset = load_preset_definition(preset_id)
    if preset:
        return preset["entries"]

    return editor_entries_to_runtime(state.entries)


def _get_valid_bone_pairs(armature, mapping_entries):
    pose_bones = armature.pose.bones
    valid_pairs = []
    missing_pairs = []

    for source_name, target_name in mapping_entries_to_pairs(mapping_entries):
        source_bone = pose_bones.get(source_name)
        target_bone = pose_bones.get(target_name)

        if source_bone and target_bone:
            valid_pairs.append((source_name, target_name, source_bone, target_bone))
        else:
            missing_pairs.append((source_name, target_name))

    return valid_pairs, missing_pairs


def _get_target_fcurves(action, target_bone_names):
    target_fcurves = []

    for fcurve in action.fcurves:
        match = BONE_DATA_PATH_RE.match(fcurve.data_path)
        if match and match.group(1) in target_bone_names:
            target_fcurves.append(fcurve)

    return target_fcurves


def _remove_target_fcurves(action, target_bone_names):
    target_fcurves = _get_target_fcurves(action, target_bone_names)
    for fcurve in list(target_fcurves):
        action.fcurves.remove(fcurve)
    return len(target_fcurves)


def _keyframe_pose_bone_visual_transform(pose_bone, frame):
    insert_options = {"INSERTKEY_VISUAL"}
    pose_bone.keyframe_insert("rotation_quaternion", frame=frame, options=insert_options)
    pose_bone.keyframe_insert("location", frame=frame, options=insert_options)
    pose_bone.keyframe_insert("scale", frame=frame, options=insert_options)


def bake_base_to_mi(context, mapping_entries=None):
    armature = context.active_object
    if not is_rig2_armature(armature):
        return False, _f("Please select a Rig2 armature")

    action = get_action(armature)
    if not action:
        return False, _f("No active action found on the Rig2 armature")

    mapping_entries = mapping_entries or _resolve_mapping_entries(context)
    valid_pairs, missing_pairs = _get_valid_bone_pairs(armature, mapping_entries)
    if not valid_pairs:
        return False, _f("No mapped Base/MI bone pairs were found on this rig")

    frames = get_keyed_frames(action, {source_name for source_name, _, _, _ in valid_pairs})
    if not frames:
        return False, _f("No keyframes found on the mapped Base bones")

    target_bone_names = {target_name for _, target_name, _, _ in valid_pairs}

    depth_groups = defaultdict(list)
    for pair in valid_pairs:
        target_bone = pair[3]
        depth_groups[_get_bone_depth(target_bone)].append(pair)

    sorted_depths = sorted(depth_groups.keys())

    scene = context.scene
    original_frame = scene.frame_current
    source_matrix_samples = {}
    removed_fcurve_count = 0

    try:
        for frame in frames:
            scene.frame_set(frame)
            context.view_layer.update()
            source_matrix_samples[frame] = {}

            for source_name, target_name, source_bone, target_bone in valid_pairs:
                source_matrix_samples[frame][source_name] = source_bone.matrix.copy()

        removed_fcurve_count = _remove_target_fcurves(action, target_bone_names)

        for _, _, _, target_bone in valid_pairs:
            target_bone.rotation_mode = "QUATERNION"

        context.view_layer.update()

        previous_quaternions = {}

        for frame in frames:
            scene.frame_set(frame)
            context.view_layer.update()

            for depth in sorted_depths:
                for source_name, target_name, source_bone, target_bone in depth_groups[depth]:
                    target_bone.matrix = source_matrix_samples[frame][source_name]

                context.view_layer.update()

            for source_name, target_name, source_bone, target_bone in valid_pairs:
                current_quaternion = target_bone.rotation_quaternion.copy()
                if target_name in previous_quaternions:
                    current_quaternion.make_compatible(previous_quaternions[target_name])
                    target_bone.rotation_quaternion = current_quaternion

                previous_quaternions[target_name] = current_quaternion.copy()
                _keyframe_pose_bone_visual_transform(target_bone, frame)
    except Exception as exc:
        return False, _f("Bake failed: {error}", error=exc)
    finally:
        scene.frame_set(original_frame)
        context.view_layer.update()

    message = _f(
        "Baked {frame_count} frames onto {pair_count} MI bones",
        frame_count=len(frames),
        pair_count=len(valid_pairs),
    )
    if removed_fcurve_count:
        message += _f(
            " (replaced {count} existing MI fcurves)",
            count=removed_fcurve_count,
        )
    if missing_pairs:
        message += _f(" ({count} mapping pairs skipped)", count=len(missing_pairs))

    return True, message


def clear_mi_bake(context, mapping_entries=None):
    armature = context.active_object
    if not is_rig2_armature(armature):
        return False, _f("Please select a Rig2 armature")

    action = get_action(armature)
    if not action:
        return False, _f("No active action found on the Rig2 armature")

    mapping_entries = mapping_entries or _resolve_mapping_entries(context)
    target_bone_names = set(mapping_entries_to_export_bones(mapping_entries))
    if not target_bone_names:
        return False, _f("No mapped MI bones were found on this rig")

    target_fcurves = _get_target_fcurves(action, target_bone_names)
    if not target_fcurves:
        return False, _f("No baked keyframes were found on the mapped MI bones")

    for fcurve in list(target_fcurves):
        action.fcurves.remove(fcurve)

    return True, _f(
        "Removed {count} fcurves from mapped MI bones",
        count=len(target_fcurves),
    )


class R2BB_OT_BakeBaseToMI(bpy.types.Operator):
    bl_idname = "r2bb.bake_base_to_mi"
    bl_label = "Bake Base -> MI"
    bl_description = "Bake world-space animation from Base bones onto mapped MI bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(context.active_object)

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}

        success, message = bake_base_to_mi(context)
        if success:
            self.report({"INFO"}, message)
            return {"FINISHED"}

        self.report({"ERROR"}, message)
        return {"CANCELLED"}


class R2BB_OT_ClearMIBake(bpy.types.Operator):
    bl_idname = "r2bb.clear_mi_bake"
    bl_label = "Clear MI Bake"
    bl_description = "Remove keyframes from the mapped MI bones used by R2BB"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(context.active_object)

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}

        success, message = clear_mi_bake(context)
        if success:
            self.report({"INFO"}, message)
            return {"FINISHED"}

        self.report({"ERROR"}, message)
        return {"CANCELLED"}


class R2BB_OT_AddMappingEntry(bpy.types.Operator):
    bl_idname = "r2bb.add_mapping_entry"
    bl_label = "Add Mapping Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}
        state.entries.add()
        return {"FINISHED"}


class R2BB_OT_RemoveMappingEntry(bpy.types.Operator):
    bl_idname = "r2bb.remove_mapping_entry"
    bl_label = "Remove Mapping Entry"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty()

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}
        if 0 <= self.index < len(state.entries):
            state.entries.remove(self.index)
            return {"FINISHED"}

        self.report({"ERROR"}, _f("Mapping row no longer exists"))
        return {"CANCELLED"}


class R2BB_OT_LoadMappingPreset(bpy.types.Operator):
    bl_idname = "r2bb.load_mapping_preset"
    bl_label = "Load Preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}
        preset = load_preset_definition(state.selected_preset or DEFAULT_PRESET_ID)
        if not preset:
            self.report({"ERROR"}, _f("Selected preset could not be loaded"))
            return {"CANCELLED"}

        set_editor_entries(state.entries, preset["entries"])
        state.selected_preset = preset["id"]
        state.preset_name = preset["name"]
        self.report({"INFO"}, _f("Loaded preset: {name}", name=preset["name"]))
        return {"FINISHED"}


class R2BB_OT_SaveMappingPreset(bpy.types.Operator):
    bl_idname = "r2bb.save_mapping_preset"
    bl_label = "Save Preset"
    bl_options = {"REGISTER", "UNDO"}

    save_as_new: bpy.props.BoolProperty(name="Save As New", default=False, options={"HIDDEN"})

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}
        runtime_entries = editor_entries_to_runtime(state.entries)

        try:
            target_preset_id = None
            if not self.save_as_new and state.selected_preset not in {DEFAULT_PRESET_ID, "", CURRENT_EDITOR_PRESET_ID}:
                target_preset_id = state.selected_preset

            preset = save_custom_preset(name=state.preset_name, entries=runtime_entries, preset_id=target_preset_id)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, _f("Could not save preset: {error}", error=exc))
            return {"CANCELLED"}

        state.selected_preset = preset["id"]
        state.preset_name = preset["name"]
        self.report({"INFO"}, _f("Saved preset: {name}", name=preset["name"]))
        return {"FINISHED"}


class R2BB_OT_DeleteMappingPreset(bpy.types.Operator):
    bl_idname = "r2bb.delete_mapping_preset"
    bl_label = "Delete Preset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "rig2_r2bb_mapping_editor", None)
        return bool(state and state.selected_preset not in {"", DEFAULT_PRESET_ID, CURRENT_EDITOR_PRESET_ID})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}
        preset = load_preset_definition(state.selected_preset)
        if not preset or preset.get("builtin"):
            self.report({"ERROR"}, _f("Only saved custom presets can be deleted"))
            return {"CANCELLED"}

        if not delete_custom_preset(preset["id"]):
            self.report({"ERROR"}, _f("Preset file could not be deleted"))
            return {"CANCELLED"}

        default_preset = load_preset_definition(DEFAULT_PRESET_ID)
        if default_preset:
            set_editor_entries(state.entries, default_preset["entries"])
        state.selected_preset = DEFAULT_PRESET_ID
        state.preset_name = default_preset["name"] if default_preset else _("Default (Built-in)")
        self.report({"INFO"}, _f("Deleted preset: {name}", name=preset["name"]))
        return {"FINISHED"}


class R2BB_OT_ImportMappingJSON(bpy.types.Operator, ImportHelper):
    bl_idname = "r2bb.import_mapping_json"
    bl_label = "Import Mapping JSON"
    bl_description = "Import mapping rows from a JSON file into the R2BB editor"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}

        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}

        filepath = Path(self.filepath)
        try:
            payload = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception as exc:
            self.report({"ERROR"}, _f("Could not read JSON: {error}", error=exc))
            return {"CANCELLED"}

        try:
            imported_name, raw_entries = _extract_import_mapping_payload(payload, filepath.stem)
            entries = normalize_mapping_entries(raw_entries)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, _f("Could not parse mapping entries: {error}", error=exc))
            return {"CANCELLED"}

        if not entries:
            self.report({"ERROR"}, _f("Imported JSON did not contain valid mapping rows"))
            return {"CANCELLED"}

        set_editor_entries(state.entries, entries)
        state.selected_preset = CURRENT_EDITOR_PRESET_ID
        state.preset_name = imported_name
        self.report(
            {"INFO"},
            _f("Imported {count} mapping rows from JSON", count=len(entries)),
        )
        return {"FINISHED"}


class R2BB_OT_ExportMappingJSON(bpy.types.Operator):
    bl_idname = "r2bb.export_mapping_json"
    bl_label = "Export Mapping JSON"
    bl_description = "Export a mapping preset to an external JSON file"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})
    filepath: bpy.props.StringProperty(name="File Path", subtype="FILE_PATH")
    mapping_preset: bpy.props.EnumProperty(
        name="Mapping Preset",
        description="Choose which mapping table should be exported",
        items=_export_preset_items,
    )

    def invoke(self, context, event):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}

        state = ensure_editor_initialized(context.scene)
        if state is None:
            self.report({"ERROR"}, _f("R2BB editor state is not available"))
            return {"CANCELLED"}

        self.mapping_preset = CURRENT_EDITOR_PRESET_ID
        base_name = state.preset_name or "r2bb_mapping"
        self.filepath = _safe_mapping_filename(base_name)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def check(self, context):
        resolved_path = _ensure_plain_json_suffix(self.filepath)
        if resolved_path != self.filepath:
            self.filepath = resolved_path
            return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mapping_preset")

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}

        mapping_entries = _resolve_mapping_entries(context, self.mapping_preset)
        state = ensure_editor_initialized(context.scene)

        if self.mapping_preset == CURRENT_EDITOR_PRESET_ID:
            preset_name = (state.preset_name if state else "") or _("Current Editor")
        else:
            preset = load_preset_definition(self.mapping_preset)
            preset_name = (preset or {}).get("name", _("Mapping Preset"))

        payload = {
            "schema_version": 1,
            "name": preset_name,
            "source_preset_id": self.mapping_preset,
            "entries": mapping_entries,
        }

        if self.mapping_preset != CURRENT_EDITOR_PRESET_ID:
            payload["id"] = self.mapping_preset

        output_path = Path(_ensure_plain_json_suffix(self.filepath))
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.report({"ERROR"}, _f("Could not write JSON: {error}", error=exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            _f("Exported {count} mapping rows to JSON", count=len(mapping_entries)),
        )
        return {"FINISHED"}


class R2BB_OT_ExportGeckoLibJSON(bpy.types.Operator):
    bl_idname = "r2bb.export_json"
    bl_label = "Export JSON"
    bl_description = "Export mapped MI bones to GeckoLib *.animation.json"

    filename_ext = ".animation.json"
    filter_glob: bpy.props.StringProperty(default="*.animation.json", options={"HIDDEN"})
    filepath: bpy.props.StringProperty(name="File Path", subtype="FILE_PATH")
    animation_name: bpy.props.StringProperty(name="Animation Name", description="Animation key written into the GeckoLib JSON", default="")
    export_format: bpy.props.EnumProperty(
        name="Bone Names",
        description="Choose which names should be written to the export",
        items=EXPORT_FORMAT_ITEMS,
        default="BASIC",
    )
    mapping_preset: bpy.props.EnumProperty(
        name="Mapping Preset",
        description="Choose which mapping table should drive this export",
        items=_export_preset_items,
    )

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(context.active_object)

    def invoke(self, context, event):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        action = get_action(context.active_object)
        self.animation_name = get_export_animation_name(action, self.animation_name)
        self.filepath = default_export_filepath(action)
        self.mapping_preset = CURRENT_EDITOR_PRESET_ID
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def check(self, context):
        resolved_path = ensure_animation_json_suffix(self.filepath)
        if resolved_path != self.filepath:
            self.filepath = resolved_path
            return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mapping_preset")
        layout.prop(self, "export_format")
        layout.prop(self, "animation_name")

    def execute(self, context):
        if not _ensure_r2bb_access(self):
            return {"CANCELLED"}
        mapping_entries = _resolve_mapping_entries(context, self.mapping_preset)
        success, message = export_geckolib_json(
            context=context,
            filepath=self.filepath,
            export_format=self.export_format,
            animation_name=self.animation_name,
            mapping_entries=mapping_entries,
        )
        if success:
            self.report({"INFO"}, message)
            return {"FINISHED"}

        self.report({"ERROR"}, message)
        return {"CANCELLED"}


classes = (
    R2BB_OT_BakeBaseToMI,
    R2BB_OT_ClearMIBake,
    R2BB_OT_AddMappingEntry,
    R2BB_OT_RemoveMappingEntry,
    R2BB_OT_LoadMappingPreset,
    R2BB_OT_SaveMappingPreset,
    R2BB_OT_DeleteMappingPreset,
    R2BB_OT_ImportMappingJSON,
    R2BB_OT_ExportMappingJSON,
    R2BB_OT_ExportGeckoLibJSON,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"R2BB register error for {cls.__name__}: {exc}")


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
