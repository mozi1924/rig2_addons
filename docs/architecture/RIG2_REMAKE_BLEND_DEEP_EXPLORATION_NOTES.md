# Rig2 Remake 深度探索笔记（第二轮）

## 1) 这轮重点：我优先深挖了哪些“小众特性”

本轮不再只看骨架/约束/材质，而是刻意寻找 Rig2 对 Blender 高阶系统的组合使用：

- `Lattice` 变形系统 + `ShapeKey`（挂在 Lattice 而不是 Mesh）
- `Curve + Hook + Spline IK` 软链条控制
- Geometry Nodes（`AIO Limbs`）并被 Driver 直接驱动节点输入
- Driver 的非脚本模式（`AVERAGE`）+ FCurve Modifier（`FNGENERATOR/GENERATOR`）
- B-Bone 多段骨 + Scripted Driver 调 bbone easing
- 骨骼自定义形状（Custom Shape）与骨骼颜色主题（palette）语义化
- `prop.*` / `Face_BlendShapes` / `stature.prop` 这类“二级属性总线”

## 2) 关键统计（全局）

- 对象类型：`MESH 61 / LATTICE 91 / CURVE 8 / EMPTY 20 / ARMATURE 1`
- Modifiers 总数：`348`
  - `LATTICE 126`
  - `ARMATURE 98`
  - `NODES 42`
  - `HOOK 28`
  - `MASK 26`
  - `SUBSURF 21`
  - `BOOLEAN 4`
- 驱动总数（全 ID 扫描）：`604`
  - `Object 514`
  - `ArmatureData 32`
  - `ShapeKeyData 56`
  - `NodeGroup 2`

Driver 类型分布：
- `AVERAGE`: 517
- `SCRIPTED`: 87

说明：Rig2 的核心并不只是“很多 Scripted Expression”，反而大量是 `AVERAGE + 变量映射`，这能降低表达式复杂度并提升可维护性。

## 3) 小众点 A：ShapeKey 全挂在 Lattice（不是 Mesh）

- `bpy.data.shape_keys`: 27
- 27/27 都归属 `LATTICE`，Mesh 上 shape key 为 0。

这意味着 Rig2 采用了“Lattice 形变中间层”，再通过 Mesh 的 Lattice Modifier 接入，避免直接在 Mesh 层堆大量 shape key。

典型链路：
- `logic["arm.bend.fix.L"]` -> `ShapeKeyData arm_bend_fix_L.key_blocks["arm_bend_fix_L"].value`
- 手指弯折：骨骼旋转（`TRANSFORMS` 变量）-> 各 finger lattice bend-fix 的 `Key 1/Key 2`
- fancy 腿：`logic["fancy_LR/UD.*"]` -> `Left/Right Leg Fancy` lattice key block 值与 mute

## 4) 小众点 B：Curve + Hook + Spline IK 组合

- Curve 对象：8（左右手臂上下段、左右腿上下段）
- Hook Modifier：28（每条 curve 多个 hook 绑定到 tweak bones）
- Pose 里 `SPLINE_IK` 约束：12

典型结构：
- `arm.spline.upper.*` / `arm.spline.lower.*` / `leg.spline.*` 骨链
- 约束目标为 `Left/Right Arm/Leg Upper/Lower Curve`
- Curve 顶点由 Hook 到 `arm.tweak.*` / `leg.tweak.*` 系列骨

这是一条“骨骼 -> Hook 曲线 -> Spline IK 骨链 -> Lattice/Mesh”的软组织路径。

## 5) 小众点 C：Geometry Nodes 被 Rig 逻辑直接驱动

Geometry Node Trees：
- `Smooth by Angle`（26 个对象使用）
- `AIO Limbs`（16 个对象使用）

`AIO Limbs` 内有 Driver 直接挂在节点输入：
- `nodes["Math"].inputs[1].default_value <- logic["bend_crease_edge"]`
- `nodes["Maths.001"].inputs[1].default_value <- logic["hands"]`

组内还直接读写命名属性 `crease_edge`：
- `GeometryNodeInputNamedAttribute` 读 `crease_edge`
- `GeometryNodeStoreNamedAttribute` 写 `crease_edge`（EDGE domain）

这属于“Rig 参数驱动几何节点属性加工”的跨系统桥接。

## 6) 小众点 D：FCurve Modifier 大量参与驱动

仅看 Armature 会低估这一点；全局统计：
- 含 FCurve Modifier 的 Driver：52
- 类型：`FNGENERATOR 46`、`GENERATOR 6`

用途示例：
- 指/拇指限制、fancy LR/UD 等逻辑通道使用 `FNGENERATOR`
- 少量 `GENERATOR(coefficients)` 做线性系数映射（如 `to_min_z = -x`）

## 7) 小众点 E：B-Bone 分段 + 驱动化 easing

- `bbone_segments > 1` 的骨骼：56
- 高分段集中在：眼睑/眉弧/嘴弧、四肢 bend 骨、Neck、Tongue

并且存在 Scripted Driver 直接驱动：
- `pose.bones[...].bbone_easein/easeout`

这说明 Rig2 把 B-Bone 当作可编程曲线骨系统来用，而非仅默认分段。

## 8) 小众点 F：属性总线不只 `logic`

除 `logic` 外，还有多套功能属性骨：

- `Face_BlendShapes`：52 属性（0..1）
  - 46 个属性被驱动网络消费（mouth/eye/brow/tongue）
- `prop.head`：13
- `prop.limbs`：9
- `prop.misc`：3
- `prop.prop`：9
- `stature.prop`：4

其中 `prop.*` 像“用户输入层”，`logic` 像“计算层”，两层解耦后再驱动约束/modifier/shape keys。

## 9) 小众点 G：骨骼 UI 语义化（Custom Shape + Palette）

- 使用 Custom Shape 的 Pose Bone：231
- Custom Shape 对象种类：24（如 `Plane`, `Ctrl_Cube`, `Limbs Tweak Shape`, `Footroll`, `Logo`）
- 骨骼颜色 palette 非默认骨有 108 条（如 `THEME08` 给 FK/手指链，`THEME07` 给 IK 上下臂）

这套系统在复杂 Rig 中非常重要：它把“功能语义”编码到可视层。

## 10) 这轮发现的可疑点（不一定是 bug）

- 某些 `AVERAGE` driver 的 `expression` 文本与变量名不一致。
  - 但这是合法的：`AVERAGE` 模式不依赖表达式字符串。
- 读取时出现 Blender 扩展卸载异常（`ice_cube_rig` 的 unregister 报错）。
  - 发生在 Blender 退出阶段，数据提取已完成。

## 11) 下一轮最值得继续读取的数据（建议顺序）

1. 形变拓扑映射图：
   - 选 1 条链路（例如 `prop.limbs -> logic -> Left Leg Fancy shape key -> Left Leg Lattice -> Left Leg mesh`）
   - 把每个中间节点、数据路径、变量名做成完整链图。

2. Spline/Hook 细节：
   - 每条 curve 的 spline 点坐标、Hook 影响点索引、falloff 半径
   - 对应 tweak 骨变换与曲线段变化关系。

3. Lattice 点级数据：
   - 对 27 个带 shape key 的 lattice，导出 key block 顶点位移量统计
   - 定量判断“弯折修正”具体改动了哪些区域。

4. Geometry Nodes 参数-效果对照：
   - `bend_crease_edge` 和 `hands` 对 AIO Limbs 输出几何的影响
   - 与 Subdivision / Sharpness / Face corner 的组合效果。

5. Driver 求值时序：
   - 在几组代表性 pose 下采样 `logic`、shape keys、constraints influence
   - 还原“从输入到结果”的每帧求值顺序与覆盖关系。

6. 运行时性能路径：
   - 统计依赖图更新热点（面部/四肢/材质）
   - 识别高开销链（例如大量 lattice + hook + spline 同时更新）。
