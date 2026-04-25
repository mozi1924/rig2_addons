# Rig2 C++ 重构目标（可作为下一轮对话起始文档）

## 1. 目标定义

本轮商业化重构的核心目标：

1. 将 `src` 与 `src/services` 中高价值纯逻辑迁移为 C++ 二进制实现。
2. Blender UI/Operator 保持 Python 壳层稳定，不直接依赖底层实现细节。
3. 二进制缺失、版本不匹配、符号不完整时，统一表现为“未解锁/不可用”，不能抛未捕获异常。
4. 逐步移除历史 Python fallback 路径，避免商业版逻辑从 Python 泄露。

---

## 2. 当前基线（已落实）

1. Native 加载入口：
   - `src/native/loader.py`
   - `src/native/face_cap_wrapper.py`
   - `src/native/miframes_wrapper.py`
2. 服务层封装：
   - `src/services/face_cap_service.py`
   - `src/services/miframes_service.py`
3. 已具备“锁定态”语义：
   - 功能不可用时返回 lock reason，不走 Python fallback。
4. 已移除：
   - `src/logic/face_cap/fallback.py`
   - `src/logic/miframes/fallback.py`

---

## 3. C++ 优先重构范围

## 3.1 第一优先级（高 ROI）

1. `miframes` 关键帧规划内核  
   Python 参考：`src/logic/miframes/planner.py`  
   C++目标：`plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)`

2. `face_cap` 协议解析与离线载入  
   Python 参考：  
   - `src/logic/face_cap/protocol.py`  
   - `src/logic/face_cap/offline_loader.py`

## 3.2 第二优先级（中 ROI）

1. `miframes` 模型注册与映射表序列化加载  
   Python 参考：`src/logic/miframes/model_registry.py`
2. `face_cap` 数据规范化与一致性比较函数组

## 3.3 保持 Python（低 ROI / 高耦合）

1. `bpy` 直接交互代码：
   - `src/modules/*/ui.py`
   - `src/modules/*/ops.py`
   - 所有 `keyframe_insert`、`pose.bones`、`context.scene` 变更路径

---

## 4. Native 接口契约（必须满足）

二进制必须通过 wrapper 的“符号校验 + API 版本校验”，否则视为未解锁。

## 4.1 `rig2_face_cap`

- 版本常量：`RIG2_FACE_CAP_API_VERSION = 1`
- 必需属性：
  - `RIG2_FACE_CAP_API_VERSION`
  - `BINARY_SUBPROTOCOL`
  - `JSON_SUBPROTOCOL`
  - `WEBSOCKET_MAGIC`
- 必需可调用符号：
  - `backend_name`
  - `clamp01`
  - `discover_local_ipv4`
  - `face_payloads_equal`
  - `parse_binary_packet`
  - `parse_packet_text`
  - `parse_schema_message`
  - `quaternions_close`
  - `resolve_transport_encoding`
  - `sanitize_head_quaternion`
  - `sniff_packet_type`
  - `load_offline_face_cap_payload`

## 4.2 `rig2_miframes`

- 版本常量：`RIG2_MIFRAMES_API_VERSION = 1`
- 必需属性：
  - `RIG2_MIFRAMES_API_VERSION`
- 必需可调用符号：
  - `backend_name`
  - `get_models`
  - `get_model_config`
  - `plan_miframes_keyframe_ops`

---

## 5. 锁定态（商业化行为）规范

1. 二进制不存在：显示未解锁。
2. 二进制存在但版本不匹配：显示未解锁 + 明确版本错误原因。
3. 二进制存在但缺符号：显示未解锁 + 明确缺失符号列表。
4. UI/Operator 不可崩溃，不得出现 Python traceback 弹窗作为用户主反馈。

---

## 6. 分阶段执行计划

## 阶段 A：契约冻结（短周期）

1. 冻结上面两组 native 接口。
2. 为接口增加 fixture 输入输出样例（JSON）。
3. 建立 C++ 与 Python 结果一致性对照测试。

## 阶段 B：`miframes` C++ 落地

1. 先实现 `plan_miframes_keyframe_ops`。
2. 再迁移 `get_models/get_model_config` 所需的数据层。
3. 在 Blender 内完成 `mi.import_action` 端到端回归。

## 阶段 C：`face_cap` C++ 落地

1. 先迁移协议解析（JSON + Binary）。
2. 再迁移离线 JSON 加载与规范化。
3. 完成实时接收与离线导入双路径回归。

## 阶段 D：去 Python 纯逻辑冗余

1. 删除已由 C++ 接管且不再用于开发调试的 Python 实现。
2. 保留最小文档化参考，不保留可直接运行的商业核心逻辑副本。

---

## 7. 验收标准（Definition of Done）

1. 功能正确性：
   - 与既有样例输出一致（允许浮点误差阈值内差异）。
2. 稳定性：
   - 缺包、错版、缺符号均为“未解锁”而非崩溃。
3. 可维护性：
   - wrapper 与 service 不出现 feature-specific 硬编码分叉扩散。
4. 商业化约束：
   - 高价值逻辑不再以可运行 Python 形式保留在发布包中。

---

## 8. 下一轮对话建议起手指令（可直接复制）

“请基于 `CPP_REFACTOR_TARGETS.md`，先实现阶段 A 的 fixture 与接口一致性测试，再进入阶段 B 的 `rig2_miframes` C++ 接口落地，严格对齐 `RIG2_MIFRAMES_API_VERSION=1` 和 required symbols。”
