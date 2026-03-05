# Mine-imator `.miframes` 文件的时间线机制分析报告

`.miframes` 是 Mine-imator 用于导出和导入关键帧动画片段（Action/Animation Clip）的专用文件格式。本文档将基于对 Mine-imator 源码的检索分析（主要围绕 [keyframes_save.gml](file:///Users/jaxlocke/Mine-imator/GmProject/scripts/keyframes_save/keyframes_save.gml) 和 [action_tl_keyframes_load_file.gml](file:///Users/jaxlocke/Mine-imator/GmProject/scripts/action_tl_keyframes_load_file/action_tl_keyframes_load_file.gml) 脚本），详细说明 `.miframes` 是如何处理时间线对齐、保存与读取机制的。

---

## 1. 数据的保存阶段 (`keyframes_save`)

当用户在 Mine-imator 中框选部分关键帧并选择导出为 `.miframes` 时，系统会执行 `keyframes_save()`，其主要处理逻辑如下：

### 1.1 识别是否为“模型动画”
系统首先会遍历所有被选中的关键帧。如果发现所选的关键帧分布在**多个不同的时间线**上（通常意味着选中了一个模型角色的多个身体部位，如头部、手臂、腿部等），系统会将内部变量 `ismodel` 标记为 `true`，以专门的模型动画模式进行保存。

### 1.2 计算相对时间位置
动画片段的时间线不是保存绝对位置，而是保存**相对位置**。
系统会找出所有被选中的关键帧中，位置最靠前的一个关键帧的位置，记为 `firstpos`（第一帧位置），并找出最靠后的位置记为 `lastpos`。
- **文件长度 (Length)**：文件的动画总长度计算为 `lastpos - firstpos`。
- **帧位置零点化**：遍历每个选中的关键帧，将其保存的时间位置 (`position`) 设定为 `当前位置 - firstpos`。这意味着无论你从时间线上的哪个位置导出动画，保存在文件里的动画时间都是从 `0` 开始起步的。

### 1.3 写入文件结构 (JSON)
系统将核心数据序列化为 JSON 格式保存。保存的核心字段包括：
* **全局元数据**：
  * `is_model` 这个动画是否关联了特定模型的骨骼层级。
  * `tempo`：导出此动画时，当前工程的帧率 (FPS)。
  * `length`：片段的持续时间长度。
* **逐帧数据 (`keyframes` 数组)**：
  * `position`：该帧的相对时间。
  * `part_name`：如果 `ismodel` 为 `true`，会额外保存该关键帧所属的身体部位名称（由 `timeline.model_part_name` 获取），以便导入时能够精准对上骨骼。
  * `values`：该关键帧具体记录的参数值（如位移、旋转、缩放等），并且只会与默认值不同的参数进行比较保存。

---

## 2. 数据的读取阶段 (`action_tl_keyframes_load_file`)

当用户将 `.miframes` 文件导入到时间线上时，系统会执行 `action_tl_keyframes_load_file()`，接收目标时间线 `tl` 以及希望插入的起始位置 `insertpos` 作为参数。

### 2.1 帧率转换与时间缩放 (Tempo Scaling)
不同工程的帧率 (Tempo) 可能不同。Mine-imator 读取 `.miframes` 时不仅加载关键帧，还会智能对其进行帧率适配。
* 系统会读取文件内的 `tempo`。
* 计算缩放比例：`temposcale = project_tempo / tempo`（当前工程帧率 / 文件保存时的帧率）。
* 文件的总长度会被缩放调整：`len = max(1, round(temposcale * len))`。

### 2.2 确定目标时间线轨道
对于读取出来的每一个关键帧数据，系统会判断应该把它放在当前工程的哪个时间线上：
* 如果文件是模型动画 (`ismodel == true`)，且当前加载帧包含 `part_name`。
* 系统会以用户当前选择的高层级时间线（`tl`）为基础，向下查找匹配该身体部位名称的子时间线：`tladd = tl_part_find(partname)`。
* 这样就确保了原来保存在右臂的帧，重新加载后依然能精准放置在当前目标模型的右臂时间线上。

### 2.3 关键帧的时间线对齐
最后一步是将关键帧安放到具体的时间上。这是由 `insertpos` 和经过缩放的相对帧位置共同决定的。
* **计算新位置**：获取文件中的原始相对 `position`。
* **应用缩放**：根据不同的帧率对位置进行调整：`pos = round(temposcale * position)`。
* **偏移到光标处**：通过 `insertpos + pos` 作为最终的放置位置。其中 `insertpos` 就是用户导入时制定的插入位置（通常对应当前时间线滑块/光标所在的时间点）。

---

## 3. 核心机制总结

Mine-imator 对于 `.miframes` 文件的处理是极其灵活且考虑到上下文的：

1. **归零相对化**：保存时剥离了环境时间位置 (`pos - firstpos`)，使动画成为与绝对时间无关的“纯净片段”。
2. **部位名称匹配 (Name-based Binding)**：对于模型动画，通过部位字符串名称 (`part_name`) 重新寻找挂载节点，而非通过生硬的 ID 或顺序寻找部件，这使得将骨骼动画复制给另一个近似但不完全相同的模型结构成为了可能。
3. **自适应帧率 (Adaptive Tempo)**：加载时能够根据文件出处和当前工程的 FPS 差异进行等比时间缩放运算 (`temposcale`)。
4. **灵活插入 (Cursor Offset)**：最终写入位置基于 `insertpos` 动态叠加，实现“指哪插哪”。
