import bpy

from ...i18n import iface as _
from .mapping import DEFAULT_PRESET_ID, get_preset_enum_items, load_preset_definition


def _preset_enum_items(self, context):
    return get_preset_enum_items(include_current=False)


class R2BB_PG_MappingEntry(bpy.types.PropertyGroup):
    base_bone: bpy.props.StringProperty(name="Base Bone", description="Rig2 Base/FK bone that should be baked from", default="")
    mi_bone: bpy.props.StringProperty(name="MI Bone", description="Mine-imator dummy bone used for bake/export", default="")
    export_name: bpy.props.StringProperty(name="Mapped Export Name", description="Bone name written to exported JSON when using preset names", default="")

    rotation_x_negative: bpy.props.BoolProperty(name="X", description="Invert exported X rotation", default=False)
    rotation_y_negative: bpy.props.BoolProperty(name="Y", description="Invert exported Y rotation", default=False)
    rotation_z_negative: bpy.props.BoolProperty(name="Z", description="Invert exported Z rotation", default=False)

    transform_x_negative: bpy.props.BoolProperty(name="X", description="Invert exported X position/scale delta", default=False)
    transform_y_negative: bpy.props.BoolProperty(name="Y", description="Invert exported Y position/scale delta", default=False)
    transform_z_negative: bpy.props.BoolProperty(name="Z", description="Invert exported Z position/scale delta", default=False)


class R2BB_PG_MappingEditorState(bpy.types.PropertyGroup):
    expanded: bpy.props.BoolProperty(name="Show Mapping Presets", default=False)
    selected_preset: bpy.props.EnumProperty(
        name="Preset",
        description="Choose a saved preset to load into the editor",
        items=_preset_enum_items,
    )
    preset_name: bpy.props.StringProperty(
        name="Preset Name",
        description="Name used when saving the current editor as a custom preset",
        default="",
    )
    entries: bpy.props.CollectionProperty(type=R2BB_PG_MappingEntry)


def entry_to_dict(entry):
    return {
        "base_bone": entry.base_bone,
        "mi_bone": entry.mi_bone,
        "export_name": entry.export_name,
        "rotation_axis_signs": {
            "X": -1.0 if entry.rotation_x_negative else 1.0,
            "Y": -1.0 if entry.rotation_y_negative else 1.0,
            "Z": -1.0 if entry.rotation_z_negative else 1.0,
        },
        "transform_axis_signs": {
            "X": -1.0 if entry.transform_x_negative else 1.0,
            "Y": -1.0 if entry.transform_y_negative else 1.0,
            "Z": -1.0 if entry.transform_z_negative else 1.0,
        },
    }


def editor_entries_to_runtime(entries):
    return [entry_to_dict(entry) for entry in entries]


def get_default_runtime_entries():
    preset = load_preset_definition(DEFAULT_PRESET_ID)
    return list(preset["entries"]) if preset else []


def get_editor_state(scene):
    return getattr(scene, "rig2_r2bb_mapping_editor", None)


def get_editor_runtime_entries(scene):
    state = get_editor_state(scene)
    if state is None:
        return get_default_runtime_entries()
    if state.entries:
        return editor_entries_to_runtime(state.entries)
    return get_default_runtime_entries()


def set_editor_entries(entries, runtime_entries):
    entries.clear()

    for runtime_entry in runtime_entries:
        item = entries.add()
        item.base_bone = runtime_entry.get("base_bone", "")
        item.mi_bone = runtime_entry.get("mi_bone", "")
        item.export_name = runtime_entry.get("export_name", "")

        rotation_signs = runtime_entry.get("rotation_axis_signs", {})
        item.rotation_x_negative = float(rotation_signs.get("X", 1.0)) < 0
        item.rotation_y_negative = float(rotation_signs.get("Y", 1.0)) < 0
        item.rotation_z_negative = float(rotation_signs.get("Z", 1.0)) < 0

        transform_signs = runtime_entry.get("transform_axis_signs", {})
        item.transform_x_negative = float(transform_signs.get("X", 1.0)) < 0
        item.transform_y_negative = float(transform_signs.get("Y", 1.0)) < 0
        item.transform_z_negative = float(transform_signs.get("Z", 1.0)) < 0


def ensure_editor_initialized(scene):
    state = get_editor_state(scene)
    if state is None:
        return None

    if state.entries:
        if not state.selected_preset:
            state.selected_preset = DEFAULT_PRESET_ID
        if not state.preset_name:
            preset = load_preset_definition(DEFAULT_PRESET_ID)
            state.preset_name = preset["name"] if preset else _("Default (Built-in)")
        return state

    runtime_entries = get_default_runtime_entries()
    set_editor_entries(state.entries, runtime_entries)
    state.selected_preset = DEFAULT_PRESET_ID
    state.preset_name = _("Default (Built-in)")
    return state


classes = (
    R2BB_PG_MappingEntry,
    R2BB_PG_MappingEditorState,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            print(f"R2BB register error for {cls.__name__}: {exc}")

    if not hasattr(bpy.types.Scene, "rig2_r2bb_mapping_editor"):
        bpy.types.Scene.rig2_r2bb_mapping_editor = bpy.props.PointerProperty(type=R2BB_PG_MappingEditorState)


def unregister():
    if hasattr(bpy.types.Scene, "rig2_r2bb_mapping_editor"):
        del bpy.types.Scene.rig2_r2bb_mapping_editor

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
