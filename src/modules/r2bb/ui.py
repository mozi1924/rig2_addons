import bpy

from ...core.registration import register_classes, unregister_classes
from ...core.utils import get_context_object, is_rig2_armature
from ...i18n import format_text as _f
from ...i18n import iface as _
from ...services.r2bb_service import get_r2bb_backend_service
from .props import get_editor_runtime_entries, get_editor_state


def _count_bake_pairs(entries):
    count = 0
    for entry in entries:
        if entry.get("base_bone") and entry.get("mi_bone"):
            count += 1
    return count


def _count_export_bones(entries):
    seen = set()
    for entry in entries:
        mi_bone = entry.get("mi_bone")
        if mi_bone:
            seen.add(mi_bone)
    return len(seen)


def _draw_axis_toggle_row(layout, label, x_prop, y_prop, z_prop, entry):
    row = layout.row(align=True)
    row.label(text=_(label))
    toggle_row = row.row(align=True)
    toggle_row.prop(entry, x_prop, text="X", toggle=True)
    toggle_row.prop(entry, y_prop, text="Y", toggle=True)
    toggle_row.prop(entry, z_prop, text="Z", toggle=True)


class R2BB_PT_ControlCenter(bpy.types.Panel):
    bl_label = "R2BB"
    bl_idname = "R2BB_PT_control_center"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_order = 60
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return is_rig2_armature(get_context_object(context))

    def draw(self, context):
        layout = self.layout
        obj = get_context_object(context)
        state = get_editor_state(context.scene)
        if state is None:
            layout.label(text=_("R2BB editor state is not registered."), icon="ERROR")
            layout.label(text=_("Try disabling and re-enabling the addon."), icon="INFO")
            return

        backend_service = get_r2bb_backend_service()
        status = backend_service.get_feature_status()
        unlocked = backend_service.is_feature_unlocked()

        if not unlocked:
            lock_box = layout.box()
            lock_box.alert = True
            lock_box.label(text=_("R2BB is disabled"), icon="ERROR")
            lock_box.label(text=status.get("message", backend_service.get_lock_reason()), icon="INFO")

        runtime_entries = get_editor_runtime_entries(context.scene)
        bake_pair_count = _count_bake_pairs(runtime_entries)
        export_bone_count = _count_export_bones(runtime_entries)

        content = layout.column()
        content.enabled = unlocked

        content.label(text=_("Bake Tools"), icon="ANIM_DATA")
        col = content.column(align=True)
        col.operator("r2bb.bake_base_to_mi", icon="ACTION")
        col.operator("r2bb.clear_mi_bake", icon="TRASH")

        content.separator()
        content.label(text=_("Export"), icon="EXPORT")
        content.operator("r2bb.export_json", icon="EXPORT")

        content.separator()
        mapping_box = content.box()
        header = mapping_box.row(align=True)
        header.prop(
            state,
            "expanded",
            text=_("Mapping Presets"),
            icon="TRIA_DOWN" if state.expanded else "TRIA_RIGHT",
            emboss=False,
        )
        header.label(text=_f("{count} bones", count=export_bone_count))

        if state.expanded:
            mapping_box.use_property_split = True
            mapping_box.prop(state, "selected_preset", text=_("Preset"))

            load_row = mapping_box.row(align=True)
            load_row.operator("r2bb.load_mapping_preset", text=_("Load Into Editor"), icon="FILE_REFRESH")
            load_row.operator("r2bb.import_mapping_json", text="", icon="IMPORT")
            load_row.operator("r2bb.export_mapping_json", text="", icon="EXPORT")

            mapping_box.prop(state, "preset_name")

            save_row = mapping_box.row(align=True)
            save_row.operator("r2bb.save_mapping_preset", text=_("Save"), icon="FILE_TICK")
            save_as = save_row.operator("r2bb.save_mapping_preset", text=_("Save As New"), icon="DUPLICATE")
            save_as.save_as_new = True
            save_row.operator("r2bb.delete_mapping_preset", text="", icon="TRASH")

            info = mapping_box.box()
            info.label(
                text=_("Each row controls bake source, MI target, export name, and axis inversion."),
                icon="INFO",
            )
            info.label(text=_f("Bake pairs: {count}", count=bake_pair_count))
            info.label(text=_f("Export bones: {count}", count=export_bone_count))
            info.label(text=_("Blank export names fall back to the MI bone name."))
            if not state.entries:
                info.label(text=_("Editor is still using the built-in preset preview."), icon="PRESET")
                info.label(text=_("Click 'Load Into Editor' before editing or saving."), icon="INFO")

            for index, entry in enumerate(state.entries):
                item_box = mapping_box.box()
                item_header = item_box.row(align=True)
                label = entry.mi_bone or entry.base_bone or _f("Mapping {index}", index=index + 1)
                item_header.label(text=label, icon="BONE_DATA")
                remove_op = item_header.operator("r2bb.remove_mapping_entry", text="", icon="X")
                remove_op.index = index

                item_col = item_box.column()
                item_col.use_property_split = True
                item_col.prop(entry, "base_bone")
                item_col.prop(entry, "mi_bone")
                item_col.prop(entry, "export_name")

                axis_col = item_box.column(align=True)
                _draw_axis_toggle_row(
                    axis_col,
                    "Invert Rotation",
                    "rotation_x_negative",
                    "rotation_y_negative",
                    "rotation_z_negative",
                    entry,
                )
                _draw_axis_toggle_row(
                    axis_col,
                    "Invert Transform",
                    "transform_x_negative",
                    "transform_y_negative",
                    "transform_z_negative",
                    entry,
                )

            mapping_box.operator("r2bb.add_mapping_entry", icon="ADD")

        content.separator()
        info_box = content.box()
        info_box.label(text=_f("Current bake pairs: {count}", count=bake_pair_count), icon="BONE_DATA")
        info_box.label(text=_f("Current export bones: {count}", count=export_bone_count), icon="ARMATURE_DATA")
        if obj and obj.animation_data and obj.animation_data.action:
            info_box.label(text=_f("Action: {name}", name=obj.animation_data.action.name), icon="ACTION")
        else:
            info_box.label(text=_("Action: None"), icon="INFO")


classes = (R2BB_PT_ControlCenter,)


def register():
    register_classes(classes, module_name="R2BB")


def unregister():
    unregister_classes(classes)
