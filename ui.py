import bpy
from .properties import PROPERTY_MAP, FRIENDLY_NAMES

def get_context_object(context):
    """
    稳健地获取当前属性面板应当显示的物体。
    支持图钉锁定、数据标签页等多种上下文。
    """
    # 优先从属性空间的 id_data 获取被锁定的 ID
    if context.area and context.area.type == 'PROPERTIES':
        id_data = context.space_data.id_data
        if id_data:
            # 如果是物体，直接返回
            if isinstance(id_data, bpy.types.Object):
                return id_data
            # 如果是骨架数据（Data 标签页），找到使用该数据的物体
            if isinstance(id_data, bpy.types.Armature):
                # 优先检查当前激活物体，看它是否使用这个数据（最快）
                if context.active_object and context.active_object.data == id_data:
                    return context.active_object
                # 否则搜索（仅在锁定状态下可能需要）
                for obj in bpy.data.objects:
                    if obj.data == id_data:
                        return obj
    
    # 降级方案：常规上下文物体
    return context.object or context.active_object

class Rig2UIDrawer:
    """公共绘图类：Properties 面板和 N 键侧边栏都调用这个方法"""
    
    @staticmethod
    def draw_prop(layout, bone, prop_name, text="", slider=True, toggle=False):
        if prop_name in bone:
            # 获取友好名称
            display_text = text or FRIENDLY_NAMES.get(prop_name, prop_name)
            if toggle:
                layout.prop(bone, f'["{prop_name}"]', text=display_text, toggle=True)
            else:
                layout.prop(bone, f'["{prop_name}"]', text=display_text, slider=slider)
            return True
        return False

    @staticmethod
    def draw_remaining_props(layout, bone, handled_set):
        internal_keys = {'_RNA_UI', 'is_rig2'}
        remaining = [k for k in bone.keys() if k not in handled_set and k not in internal_keys]
        if remaining:
            sublog = layout.column(align=True)
            sublog.label(text="Additional Props:", icon='ADD')
            for k in remaining:
                sublog.prop(bone, f'["{k}"]', slider=True)

    @staticmethod
    def draw_limbs(layout, context):
        obj = get_context_object(context)
        if not obj or obj.type != 'ARMATURE': return
        pose_bones = obj.pose.bones
        handled = set()
        if "prop.limbs" in pose_bones:
            bone = pose_bones["prop.limbs"]
            row = layout.row()
            col = row.column(align=True)
            for p in ["arm-L-fk-ik", "arm-L-wrist-ik", "leg-L-fk-ik"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in ["arm-R-fk-ik", "arm-R-wrist-ik", "leg-R-fk-ik"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            row = layout.row(align=True)
            for p in ["arm-world-ik", "ik-stretch.arm", "ik-stretch.leg"]:
                if Rig2UIDrawer.draw_prop(row, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_head(layout, context):
        obj = get_context_object(context)
        if not obj or obj.type != 'ARMATURE': return
        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        if "prop.head" in pose_bones:
            bone = pose_bones["prop.head"]
            layout.prop(rig_props, "lash_enum", icon='STRANDS')
            handled.add("lash")
            row = layout.row()
            col = row.column(align=True)
            for p in ["jaw", "eyebrow_width", "mouth_shape"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            col = row.column(align=True)
            for p in ["neck_length", "eye_tracker", "brow_auto_rotation"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["Tongue", "enable_neck", "eyebrow", "inherit_rotation", "layout_mode", "panel_to_face"]:
                if Rig2UIDrawer.draw_prop(grid, bone, p, toggle=True): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_misc(layout, context):
        obj = get_context_object(context)
        if not obj or obj.type != 'ARMATURE': return
        pose_bones = obj.pose.bones
        rig_props = obj.rig2_props
        handled = set()
        if "prop.misc" in pose_bones:
            bone = pose_bones["prop.misc"]
            row = layout.row()
            if Rig2UIDrawer.draw_prop(row, bone, "alex", toggle=True): handled.add("alex")
            if Rig2UIDrawer.draw_prop(row, bone, "hands", toggle=True): handled.add("hands")
            layout.prop(rig_props, "feet_enum", text="Ankle/Feet Style")
            handled.add("feet_style")
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

    @staticmethod
    def draw_perf(layout, context):
        obj = get_context_object(context)
        if not obj or obj.type != 'ARMATURE': return
        pose_bones = obj.pose.bones
        handled = set()
        if "prop.prop" in pose_bones:
            bone = pose_bones["prop.prop"]
            grid = layout.grid_flow(columns=2, align=True)
            for p in ["enable_left_eye", "enable_right_eye", "enable_left_mouth", "enable_right_mouth"]:
                if Rig2UIDrawer.draw_prop(grid, bone, p): handled.add(p)
            col = layout.column(align=True)
            for p in ["view_body_boolen", "render_body_boolen", "view_face_boolen", "render_face_boolen", "view-subdivision", "render-subdivision"]:
                if Rig2UIDrawer.draw_prop(col, bone, p): handled.add(p)
            Rig2UIDrawer.draw_remaining_props(layout, bone, handled)

# --- Properties Panel Classes ---

class RIG2_PT_BasePanel:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_order = -10
    
    @classmethod
    def poll(cls, context):
        obj = get_context_object(context)
        if obj and obj.type == 'ARMATURE':
            if obj.pose and "logic" in obj.pose.bones:
                bone = obj.pose.bones["logic"]
                return bone.get("is_rig2") == 1
        return False

class RIG2_PT_MainPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Rig/2 Control Center"
    bl_idname = "RIG2_PT_main_panel"

    def draw(self, context):
        layout = self.layout
        layout.operator("rig2.reset_props", text="Reset All Defaults", icon='LOOP_BACK')

class RIG2_PT_LimbsPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Limbs & IK-FK Switch"
    bl_idname = "RIG2_PT_limbs_panel"
    bl_parent_id = "RIG2_PT_main_panel"

    def draw(self, context):
        Rig2UIDrawer.draw_limbs(self.layout, context)

class RIG2_PT_HeadPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Face & Head Details"
    bl_idname = "RIG2_PT_head_panel"
    bl_parent_id = "RIG2_PT_main_panel"

    def draw(self, context):
        Rig2UIDrawer.draw_head(self.layout, context)

class RIG2_PT_AdvancedPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Performance & Settings"
    bl_idname = "RIG2_PT_advanced_panel"
    bl_parent_id = "RIG2_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        pass

class RIG2_PT_MiscPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Character Style"
    bl_idname = "RIG2_PT_misc_panel"
    bl_parent_id = "RIG2_PT_advanced_panel"

    def draw(self, context):
        Rig2UIDrawer.draw_misc(self.layout, context)

class RIG2_PT_PerfPanel(RIG2_PT_BasePanel, bpy.types.Panel):
    bl_label = "Optimization"
    bl_idname = "RIG2_PT_perf_panel"
    bl_parent_id = "RIG2_PT_advanced_panel"

    def draw(self, context):
        Rig2UIDrawer.draw_perf(self.layout, context)

classes = (
    RIG2_PT_MainPanel,
    RIG2_PT_LimbsPanel,
    RIG2_PT_HeadPanel,
    RIG2_PT_AdvancedPanel,
    RIG2_PT_MiscPanel,
    RIG2_PT_PerfPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
