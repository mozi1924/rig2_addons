---
lang: zh
categories: ["Blender", "Rig2", "开发记录"]
title: "Rig2 Remake Blend 资产解析：骨架、驱动与材质系统拆解"
date: "2026-05-03"
desc: "基于 Blender 4.5.9 LTS 对 rig2-remake.blend 的结构化解析，覆盖骨架分层、驱动职责分布、材质节点链路与后续重构建议。"
image: "../../assets/rig2-ecosystem-dev-months/cover.webp"
---

# Rig2 Remake Blend 资产解析文档

## 1. 解析范围与方法

- 资产文件：`assets/rig2-remake.blend`
- 解析工具：`/Applications/Blender.app/Contents/MacOS/Blender`
- 解析方式：Blender 后台 Python 脚本读取 `bpy.data`，提取
  - Armature（骨架结构、Pose 约束、自定义属性）
  - Drivers（对象级 + Armature 数据级）
  - Material（节点树 + Node Group）

当前文档基于 2026-05-03 的本地解析结果（Blender 4.5.9 LTS）。

## 2. 总览（关键统计）

- 对象总数：181
- Armature：1（`Rig2 Armature`）
- 骨骼数量：729
- Pose 约束总数：852
- 驱动器总数：440
  - Object 驱动：408
  - Armature Data 驱动：32（全部用于 Bone Collection 可见性）
- 材质数量：1（`rig2_material`）
  - 外层节点数：23
  - 外层连线数：28

驱动用途拆分：
- `logic` 属性计算：109
- 约束通道（如 influence / min_y / to_min_y）：287
- 骨骼集合可见性：32
- 其他 Pose 通道：12

## 3. 骨架结构（Armature）

## 3.1 顶层骨骼模块（root 子树）

按子树规模看，核心 root：

- `scale`：363（身体/四肢主链 + 变体映射）
- `Face panel Parent`：89（面部控制面板）
- `Eye`：70（眼球/眼睑/眼部表情）
- `Eye.shape`：49（眼部形状驱动链）
- `Mouth`：39（嘴型与口部 BS）
- `crontrol`：28（拼写即资产原名，控制父级中枢）
- `Jaw`：28（下颌与牙齿联动）
- `Mouth.shape`：22（嘴型 shape 系统）

此外存在多个独立 root（如 `logic`、`MI_*` target、若干 tweak / panel 辅助骨）。这说明该 Rig 不是单树状，而是“多子系统并列 + 约束/驱动耦合”的架构。

## 3.2 骨骼命名分布（前缀计数）

高频前缀：

- `Eye`: 147
- `Mouth`: 96
- `arm`: 68
- `leg`: 66
- `Eyebrow`: 42
- 手指系（`index`/`middle`/`ring`/`pinky`/`thumb`）合计：90
- `MI_arm`: 14
- `MI_leg`: 14

结论：该资产明显偏“面部控制 + Minecraft 风格肢体映射”的复合 Rig，而不是仅身体动画骨架。

## 3.3 Bone Collection 分层

顶层 Collection：

- `Rig 2 Base`
- `Rig 2 Crontrol`
- `Shapes`
- `Dummy Bones`
- `Unlisted`

其中：
- `Rig 2 Base` 下分 Body / Left Arm / Right Arm / Left Leg / Right Leg
- `Rig 2 Crontrol` 下分中心骨、左右四肢控制、头部草图控制、浮动面板、眼追踪等
- `Unlisted` 中包含 `Logic` 与 `position`

这与驱动系统配合后形成“按模式显隐控制器”的 UI 体验（见第 4.4 节）。

## 4. 驱动器系统（重点：`logic` 骨骼自定义属性）

## 4.1 `logic` 骨骼定位

- `logic` 本身是 root 骨，几乎不参与层级变换。
- 它承担“状态总线 / 中间变量层”角色：
  - 直接可调参数（用户控制）
  - 计算后的派生参数（供约束/显隐消费）
- `logic` 自定义属性共 125 个。

## 4.2 `logic` 属性网络特征

- 109 条驱动用于写入 `pose.bones["logic"]["..."]`。
- 287 条驱动读取 `logic` 属性并驱动约束或集合可见性。
- 即：`logic` 作为“计算中间层”把输入和执行层解耦。

高扇出属性（被下游大量消费）：

- `face_cap`：26
- `mi_mapping_mode`：20
- `feet_style`：12
- `limbs_state3`：10
- `r-mouth_shape`：9
- `face_slimming`：8
- `is_arm_ik_L` / `is_arm_ik_R` / `eye_tweak.L` / `eye_tweak.R`：各 7

## 4.3 关键驱动逻辑（公式示例）

### 四肢 IK/FK 与模式切换

- `is_arm_ik_L = arm_L_fk_ik * (-limbs_state3+1)`
- `is_arm_fk_L = (-arm_L_fk_ik+1) * (-limbs_state3+1)`
- `is_leg_ik_L = leg_L_fk_ik * (-limbs_state3+1)`
- `is_leg_fk_L = (-leg_L_fk_ik+1) * (-limbs_state3+1)`

说明：使用显式派生布尔值，避免把复杂表达式分散写到每个约束。

### 脚部风格与踝部逻辑

- `feet_style` 注释语义：`-1 off | 0 ankle | 1 fancy`
- `ankle-ik.L = (feet_style == 0) * ik`
- `fancy_feet.L = (feet_style == 1) or (feet_style == -1)`
- `disable_fancy.L = (-fancy_feet_L+1) or (feet_style == -1)`

说明：同一套腿链支持 normal/fancy/off 等模式，通过中间状态统一分发。

### 伸缩与弯折修正

- `leg_stretch.L = ik_stretch_leg * is_leg_ik_L * (feet_style != 1)`
- `ik-stretch.arm.L = ik_stretch_arm * is_arm_ik_L`
- `arm.bend.fix.L = tan(var/2)*value`
- `leg.bend.fix.L = tan(var/2)*value`

说明：把弯折补偿与 IK 伸缩开关独立成逻辑属性，便于调优。

### 面部与口型

- `r-mouth_shape = -mouth_shape+1`
- `jaw_x_cjm = jaw * cjm`
- `mouth.side.half.up = var * shape`
- `lash_1..lash_6 = min(abs(lash_style - n), 1)`

说明：大量使用互补值（`r-*`）与离散索引（睫毛样式），减少下游条件判断。

## 4.4 集合显隐驱动（控制器 UI 层）

Armature Data 上 32 条驱动均用于 `collections_all[...].is_visible`，典型映射：

- `Left Arm IK` <- `is_arm_ik_L`
- `Left Arm FK` <- `is_arm_fk_L`
- `Left/Right Fingers Alex` <- `hands_alex`
- `Left/Right Fingers Steve` <- `hands_steve`
- `MI_Mapping` <- `show_mi`
- `BlendShapes` <- `face_cap`

说明：模式切换时，控制骨集合自动显隐，用户界面随状态变化，降低误操作。

## 5. 约束系统（值得关注）

## 5.1 约束类型分布

高频约束：

- `TRANSFORM`: 283
- `COPY_TRANSFORMS`: 190
- `COPY_ROTATION`: 102
- `LIMIT_LOCATION`: 71
- `STRETCH_TO`: 65
- `DAMPED_TRACK`: 45

说明：Rig 设计偏“转换映射 + 拷贝融合”，而非大量纯 IK 求解。

## 5.2 四肢约束范式

以 `arm.upper.L` 为例：
- `FK (COPY_ROTATION)`
- `IK (COPY_ROTATION)`
- `FK Copy Location`
- `MI_Mapping (COPY_TRANSFORMS)`

以 `leg.lower.L` 为例：
- `FK`
- `IK-normal`
- `IK-Fancy`
- `MI_Mapping`

设计上是多来源姿态并存，再由 `logic` 驱动 influence 混合。

## 5.3 空间切换与本地/世界切换

`arm.ik.parent.L/R` 上同时挂两个 `CHILD_OF`：

- `world` -> `center`
- `local` -> `arm.root.L/R`

`logic` 属性 `arm-world-ik` 与 `r-arm-world-ik` 分别控制两者 influence，实现无缝空间切换。

## 5.4 面部约束密度高

约束最密集骨骼集中在：

- `eye.BS.L/R`
- `Mouth.upper/lower.*.BS*`
- `pupil.panel.L/R`
- `eyebrow.BS.L/R`

说明面部表现主要由“控制面板骨 + BlendShape 约束权重驱动”实现。

## 6. AIO 材质节点树

## 6.1 外层材质图（`rig2_material`）

外层节点树职责：

- 接入贴图（`steve texture`、眼部贴图、SSS 贴图）
- 接入 UV 与程序化遮罩（Eye LR / Pupil.inside）
- 将颜色层（Color 1~6）与 Mask 输入 AIO 组
- 最终连接到 Material Output Surface

## 6.2 Node Group 依赖结构（递归）

主要组结构：

- `rig2_material`（32 节点 / 58 连线）
  - 子组：`Skin`, `Eye`, `Teeth`, `Gay Ball`
- `Eye`（12 / 29）
  - 子组：`Eye Procedural textures`
- `Eye Procedural textures`（18 / 33）
  - 子组：`Pupil Factory`, `Pupil Mixer`
- `Pupil Factory`（8 / 15）
  - 子组：`Pupil UV`, `Pupil.inside`
- `Pupil.inside`（15 / 21）
  - 数学主导（9 个 Math 节点）

## 6.3 AIO 组输入语义

`rig2_material` 组输入包含：

- 角色基础外观：`Skin`, `Eye`, `Brow`, `Eye White`, `Alpha`
- 发光与 SSS：`Emission Color/Strength`, `Subsurface Scattering*`
- 程序化配色：`Color 1~6`, `Size 1~5`, `Mask`
- 细节开关：`Teeth Gaps`, `Use Texrure`, `Scale`

说明：AIO 组把“材质逻辑集中化”，上层只负责喂参数与贴图，便于跨角色复用。

## 7. 为什么这样设计（推断）

## 7.1 `logic` 作为中间总线

如果每个约束直接读用户控件，会出现：
- 表达式重复
- 互补值（如 `x`/`1-x`）重复计算
- 模式切换难以统一

当前方案先把输入归一到 `logic`，再由下游消费，明显更可维护。

## 7.2 骨骼集合显隐自动化

大量 collection visibility 驱动的目标是“让操作者只看到当前模式所需控件”，这是可用性设计，不是单纯技术实现。

## 7.3 面部与身体解耦

面部（高密度约束/BS）与身体（IK/FK/Stretch）通过 `logic` 汇合，但骨架拓扑相对独立，有助于单独迭代面部功能。

## 7.4 MI 映射兼容层

`mi_mapping_mode`、`show_mi`、`MI_*` 骨与 `COPY_TRANSFORMS` 约束组合，体现出该 Rig 需要在 Rig2 与 MI 工作流之间切换兼容。

## 8. 维护建议（给后续开发）

- 新增模式开关时，优先新增 `logic` 派生属性，而不是把表达式分散到每条约束。
- `r-*` 互补属性建议保持命名一致，避免后续驱动命名漂移。
- Collection 可见性驱动应继续集中在 Armature Data，避免混入对象级驱动。
- 面部模块改动前，先检查 `face_cap` 与 `r-mouth_shape` 的扇出链路，避免级联回归。
- 材质层面优先改 Node Group 内逻辑，尽量保持外层接口稳定。

## 9. 附录：常用定位点

- 主 Armature 对象：`Rig2 Armature`
- 逻辑骨：`logic`
- 主材质：`rig2_material`
- 关键模式属性：
  - `arm-L-fk-ik`, `arm-R-fk-ik`, `leg-L-fk-ik`, `leg-R-fk-ik`
  - `feet_style`, `mi_mapping_mode`, `show_mi`, `face_cap`
  - `panel_to_face`, `mouth_shape`, `jaw`, `lash_style`
## 10. 附录：logic 自定义属性完整清单（125 项）

格式：`属性名 = 当前值  [min, max]`

```text
Complete_jaw_movement = 1.0  [0.0, 1.0]
Tongue = 1.0  [0.0, 1.0]
Tooth_occlusion = 0.4999999403953552  [0.0, 1.0]
alex = 0.0  [0.0, 1.0]
ankle-fk.L = 0.0  [0.0, 1.0]
ankle-fk.R = 0.0  [0.0, 1.0]
ankle-ik.L = 1.0  [0.0, 1.0]
ankle-ik.R = 1.0  [0.0, 1.0]
ankle.L = 1.0  [0.0, 1.0]
ankle.R = 1.0  [0.0, 1.0]
arm-L-fk-ik = 0.0  [0.0, 1.0]
arm-L-wrist-ik = 0.0  [0.0, 1.0]
arm-R-fk-ik = 0.0  [0.0, 1.0]
arm-R-wrist-ik = 0.0  [0.0, 1.0]
arm-world-ik = 0.0  [0.0, 1.0]
arm.bend.fix.L = 0.0  [0.0, 2.0]
arm.bend.fix.R = 0.0  [0.0, 2.0]
bend_crease_edge = 1.0  [0.0, 1.0]
bend_value = 1.0  [0.0, 2.0]
boolen_render_body = 1.0  [0.0, 1.0]
boolen_render_face = 1.0  [0.0, 1.0]
boolen_view_body = 1.0  [0.0, 1.0]
boolen_view_face = 1.0  [0.0, 1.0]
brow_auto_rotation = 1.0  [0.0, 1.0]
disable_fancy.L = 1.0  [0.0, 1.0]
disable_fancy.R = 1.0  [0.0, 1.0]
enable_left_eye = 1.0  [0.0, 1.0]
enable_mouth = 1.0  [0.0, 1.0]
enable_neck = 0.0  [0.0, 1.0]
enable_right_eye = 1.0  [0.0, 1.0]
eye_tracker = 0.0  [0.0, 1.0]
eye_tracker_head = 0.0  [0.0, 1.0]
eye_tweak.L = -0.09950000047683716  [-1.0, 1.0]
eye_tweak.R = -0.09950000047683716  [-1.0, 1.0]
eyebrow = 1.0  [0.0, 1.0]
eyebrow_width = 0.6000000238418579  [0.0, 1.0]
face_cap = 0.0  [0.0, 1.0]
face_cap_hr = 1.0  [0.0, 1.0]
face_slimming = 0.0  [0.0, 0.20000000298023224]
fancy_LR.L = -1.4210853021136109e-14  [-1.0, 1.0]
fancy_LR.R = 1.4210853021136109e-14  [-1.0, 1.0]
fancy_UD.L = 0.0  [-1.0, 1.0]
fancy_UD.R = 0.0  [-1.0, 1.0]
fancy_feet.L = 0.0  [0.0, 1.0]
fancy_feet.R = 0.0  [0.0, 1.0]
fancy_fk.L = 0.0  [0.0, 1.0]
fancy_fk.R = 0.0  [0.0, 1.0]
fancy_leg_stretch.L = 0.0  [0.0, 1.0]
fancy_leg_stretch.R = 0.0  [0.0, 1.0]
feet_style = 0  [-1, 1]
finger_limit.L = 0.0  [-1.0, 1.0]
finger_limit.R = 0.0  [-1.0, 1.0]
fk_wrist.L = 1.0  [0.0, 1.0]
fk_wrist.R = 1.0  [0.0, 1.0]
footroll.L = 1.0  [0.0, 1.0]
footroll.R = 1.0  [0.0, 1.0]
hands = 0.0  [0.0, 1.0]
hands_alex = 0.0  [0.0, 1.0]
hands_steve = 0.0  [0.0, 1.0]
head_inherit_rotation = 1.0  [0.0, 1.0]
ik-stretch.arm = 0.0  [0.0, 1.0]
ik-stretch.arm.L = 0.0  [0.0, 1.0]
ik-stretch.arm.R = 0.0  [0.0, 1.0]
is_arm_fk_L = 1.0  [0.0, 1.0]
is_arm_fk_R = 1.0  [0.0, 1.0]
is_arm_ik_L = 0.0  [0.0, 1.0]
is_arm_ik_R = 0.0  [0.0, 1.0]
is_leg_fk_L = 0.0  [0.0, 1.0]
is_leg_fk_R = 0.0  [0.0, 1.0]
is_leg_ik_L = 1.0  [0.0, 1.0]
is_leg_ik_R = 1.0  [0.0, 1.0]
is_rig2 = 1  [1, 1]
jaw = 0.4000000059604645  [0.0, 1.0]
jaw_mid_track = 0.0  [0.0, 1.0]
jaw_side_track = 1.0  [0.0, 1.0]
jaw_x_cjm = 0.4000000059604645  [0.0, 1.0]
lash_1 = 0  [0, 1]
lash_2 = 1  [0, 1]
lash_3 = 1  [0, 1]
lash_4 = 1  [0, 1]
lash_5 = 1  [0, 1]
lash_6 = 1  [0, 1]
lash_style = 1  [0, 6]
layout_mode = 0.0  [0.0, 1.0]
leg-L-fk-ik = 1.0  [0.0, 1.0]
leg-R-fk-ik = 1.0  [0.0, 1.0]
leg-fancy-ik.L = 0.0  [0.0, 1.0]
leg-fancy-ik.R = 0.0  [0.0, 1.0]
leg-ik.L = 1.0  [0.0, 1.0]
leg-ik.R = 1.0  [0.0, 1.0]
leg.bend.fix.L = 0.0  [0.0, 2.0]
leg.bend.fix.R = 0.0  [0.0, 2.0]
leg_stretch.L = 0.0  [0.0, 1.0]
leg_stretch.R = 0.0  [0.0, 1.0]
limbs_state3 = 0.0  [0.0, 1.0]
mi_ik_arm.L = 0.0  [0.0, 1.0]
mi_ik_arm.R = 0.0  [0.0, 1.0]
mi_ik_leg.L = 0.0  [0.0, 1.0]
mi_ik_leg.R = 0.0  [0.0, 1.0]
mi_mapping_mode = 0.0  [0.0, 1.0]
mouth.side.half.up = 0.0  [0.0, 1.0]
mouth_shape = 0.0  [0.0, 1.0]
panel_to_face = 0.0  [0.0, 1.0]
pupil_AT.L = 0.0  [-1.0, 1.0]
pupil_AT.R = 0.0  [-1.0, 1.0]
r-alex = 1.0  [0.0, 1.0]
r-ankle-fk.L = 1.0  [0.0, 1.0]
r-ankle-fk.R = 1.0  [0.0, 1.0]
r-ankle-ik.L = 0.0  [0.0, 1.0]
r-ankle-ik.R = 0.0  [0.0, 1.0]
r-ankle.L = 0.0  [0.0, 1.0]
r-ankle.R = 0.0  [0.0, 1.0]
r-arm-world-ik = 1.0  [0.0, 1.0]
r-eye_tweak.L = -0.09650000184774399  [-1.0, 1.0]
r-eye_tweak.R = -0.09650000184774399  [-1.0, 1.0]
r-hands = 1.0  [0.0, 1.0]
r-mouth_shape = 1.0  [0.0, 1.0]
r-panel_to_face = 1.0  [0.0, 1.0]
r-pupil_AT.L = 0.0  [-1.0, 1.0]
r-pupil_AT.R = 0.0  [-1.0, 1.0]
r2mi = 0.0  [0.0, 1.0]
real_minecraft_size = 1.0  [0.0, 1.0]
show_mi = 0.0  [0.0, 1.0]
thumb_limit.L = 0.0  [-1.0, 1.0]
thumb_limit.R = 0.0  [-1.0, 1.0]
```
