# Mine-imator `.miobject` 与 `.miframes` 关键帧映射对照与分析报告

为了验证您在 Blender (Rig2) 插件里对于 `.miobject` 和 `.miframes` 两种文件的读取逻辑是否正确，我分析了 Mine-imator 源码中控制 `.miobject` 导出的 [project_save_timeline.gml](file:///Users/jaxlocke/Mine-imator/GmProject/scripts/project_save_timeline/project_save_timeline.gml) 以及相关的加载机制。

`.miobject` 与 `.miframes` 在代码设计上具有**根本性的不同**：`.miframes` 像是“提纯后的动作切片”，而 `.miobject` 是一个“微型工程（Mini-Project）”。

以下是判断您的 Blender 映射解析是否正确的**核心校验清单**：

---

## 1. 整体数据结构的差异
对于您的 Blender 净库读取脚本来说，必须针对这两种文件采用截然不同的解包方案：

* **.miframes**：
  核心关键帧位于根节点的 `keyframes` 数组下。这是一个扁平化的一维数组，所有的关键帧（无论属于什么身体部位）都混在同一个数组里。文件根节点会指明 `{"is_model": true}` 和全局帧率 `tempo`。
* **.miobject**：
  核心关键帧是**分散的**。根节点存在 `timelines`、`templates`、`resources` 数组。您需要遍历 `timelines` 数组，因为每个 Timeline 对象都独立包含自己的属性及其内部专属的 `keyframes` 节点。

## 2. 角色部位映射 (`part_name` 匹配) 规则的不同

**在 `.miframes` 中 (纯动画片段)：**
每个具体的关键帧拥有自己的 `part_name` 属性（如 `{"position": 10, "part_name": "LeftArm", "values": {...}}`）。身体部位名称是由每一帧自己携带的。

**在 `.miobject` 中 (实体对象)：**
关键帧自身**不携带**任何部位名称！
部位名称是绑定在**时间线 (Timeline) 级**上的。
* 您需要遍历 `.miobject` 里面的每一个 Timeline。
* 检查该 Timeline 的 `type` 属性（通常角色的部位是 `"bodypart"`），并读取它的 `model_part_name` 字段。
* **判定结论**：只要这个 Timeline 具有 `model_part_name` (例如 `"Head"`)，那么它底下的 **所有关键帧** 就都是属于 `"Head"` 骨骼控制的。
* *在 Blender 中的实现注意*：建立 `<model_part_name>` -> `<Bone Name>` 的骨骼字典时，处理 `.miobject` 应处于解析 Timeline 循环的层级，而不是单帧循环的层级。

## 3. 关键帧列表的存储格式不同 (数组 vs 字典)

**在 `.miframes` 中：**
`keyframes` 是一个 Array。如：
```json
"keyframes": [
  {"position": 0, "values": {...}},
  {"position": 10, "values": {...}}
]
```

**在 `.miobject` 中（极其重要！）：**
根据源码 [project_save_timeline.gml](file:///Users/jaxlocke/Mine-imator/GmProject/scripts/project_save_timeline/project_save_timeline.gml) 第 `91-102` 行：
```gml
json_save_object_start("keyframes")
for (var k = 0; k < ds_list_size(keyframe_list); k++) {
    project_save_values(string(position), value, other.value_default)
}
```
这意味着在 `.miobject` 中，`keyframes` 是一个**对象/字典 (Object/Dictionary)**。**它的 Key 是由帧的时间位置转成的字符串**，Value 直接是具体的参数集合：
```json
"keyframes": {
  "0": { "ROT_X": 15.0, "POS_Y": 2.0 },
  "12": { "ROT_X": -15.0, "POS_Y": 3.0 }
}
```
*在 Blender 中的实现注意*：如果您用解析 `.miframes` 列表的方法去迭代 `.miobject` 的关键帧，必然会引发类型报错！您需要使用 `for key, value in keyframes.items():` 获取 `position` 并将其转回整数。

## 4. 时间位置 (`position`) 的偏移差异

**在 `.miframes` 中（相对化局部坐标）：**
如上一个报告所述，它经过了归零化处理（`position - firstpos`）。动画严格从 0 开始。

**在 `.miobject` 中（绝对全局坐标）：**
`.miobject` 保存的时间线是绝对的。当初在这个模型在导出者的工程的第 360 帧，它现在存进文件的数值也就是 `"360": {...}`。
*在 Blender 中的实现注意*：如果要在 Blender 里正确应用从 `.miobject` 里提取出来的关键帧，您必须自己找到该文件里最小的时间 Key 作为起步偏移 `firstpos = min([int(k) for k in keyframes.keys()])`，并在打关键帧时将所有的帧都减去这个数值（或者利用用户当前光标位置进行加上偏移），否则动作可能会被打到几千帧的远处。

## 5. 参数继承与覆盖 (Inherit/Lock)
在 `.miobject` 的 Timeline 解析中，您会发现 `inherit` 字段（如 `inherit_rotation`, `inherit_position`）。这代表 Mine-imator 空间内的层级约束。由于 Blender 自带 FK 骨骼层级系统（父子骨骼），这部分通常您现有的骨骼驱动就可以默认解决，不需要强行将旋转进行约束解除。但在映射时如果发现某些特殊方块不受控，可能是因为导出的对象关闭了继承 (`inherit_xx = false`)。

---

### 总结 Checklist 供您对照代码：
1. [ ] 读取 `.miobject` 时，进入的是 `timelines` 列表而不是根级 `keyframes`。
2. [ ] 解析对象部位不是逐帧寻找 `part_name`，而是获取当前 Timeline 对象的 `model_part_name`。
3. [ ] 遍历关键帧时，代码处理的是 `Dict`（字典 KV 对），且 Key = 时间点。
4. [ ] 处理 Timeline 的绝对帧数：将离散的帧减去了最初的偏置，以便在 Blender 当下光标位置播放动作。
