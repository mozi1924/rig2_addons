# Rig2 C++ 性能优化任务文档（面向多会话并行推进）

## 1. 文档目标

本任务文档用于把当前 C++ 重构从“逆向门槛提升”扩展为“可量化性能收益”，并支持在不同会话中分别推进：

1. `face_cap` 高频实时链路优化。
2. `miframes` 规划与数据通路优化。

文档强调分阶段、可回归、可比较、可回滚。

---

## 2. 当前基线与瓶颈判断

基线现状（截至 2026-04-25）：

1. `miframes` 核心规划已迁入 C++：
   - `native_cpp/src/rig2_miframes.cpp`
2. `face_cap` 部分解析逻辑已在 C++：
   - `native_cpp/src/rig2_face_cap.cpp`
3. 实时 WebSocket 接收主链路仍在 Python：
   - `src/modules/face_cap/runtime.py`

主要瓶颈：

1. `face_cap` 收包/解包/对象构造仍经过 Python 线程 + Python 对象路径。
2. `miframes` C++ 入口中仍有较多 Python dict/list 层交互与临时对象构建。
3. 缺少标准化性能基准，导致“优化是否有效”不可量化。

---

## 3. 总体优化目标（必须量化）

所有优化必须通过同一套 benchmark 对比 before/after，指标包括：

1. 吞吐：`msgs/s`（单客户端、4 客户端、8 客户端）。
2. 延迟：`p50/p95/p99`（接收至可消费快照）。
3. CPU：插件进程 CPU 占用（均值与峰值）。
4. 稳定性：长时间运行（>= 30 分钟）无崩溃、无死锁、无内存异常增长。
5. 行为一致性：业务语义与既有路径一致（在误差阈值内）。

建议目标（第一轮）：

1. `face_cap` 吞吐提升 >= 2x。
2. `face_cap` p99 延迟下降 >= 30%。
3. `miframes` 规划耗时下降 >= 25%。
4. 同负载下 CPU 降低 >= 20%。

---

## 4. 多会话拆分策略

你将在不同会话推进两条主线，建议严格分离改动面，避免相互阻塞。

### 会话线 A：`face_cap` 性能优化（实时链路）

职责边界：

1. 负责 `face_cap` 实时接收与快照获取路径。
2. 不修改 `miframes` 相关逻辑。
3. 不改动 UI 语义，仅调整底层 service/runtime 调用。

涉及路径：

1. `native_cpp/src/rig2_face_cap.cpp`
2. `src/services/face_cap_service.py`
3. `src/modules/face_cap/runtime.py`
4. `tests/` 下新增 face_cap 性能与契约测试

### 会话线 B：`miframes` 性能优化（规划链路）

职责边界：

1. 负责 `miframes` 规划函数和数据传输路径。
2. 不修改 `face_cap` runtime 与网络层。
3. 保持 operator/UI 入口行为不变。

涉及路径：

1. `native_cpp/src/rig2_miframes.cpp`
2. `src/services/miframes_service.py`
3. `src/modules/rig_controls/miframes/importer.py`（仅适配层）
4. `tests/` 下新增 miframes 基准与一致性测试

---

## 5. 阶段计划（两条线共用）

## 阶段 P0：基准与观测先行（必须先做）

交付：

1. 新增可重复 benchmark 脚本（固定输入、固定轮次、固定输出格式）。
2. 固化 baseline 报告（时间戳、机器信息、commit hash）。
3. 新增最小监控统计结构（包计数、丢弃计数、耗时分位数）。

完成判定：

1. 同一命令重复执行 3 次，结果波动在可接受区间。
2. 报告可用于后续每阶段横向比较。

## 阶段 P1：低风险高收益优化

`face_cap` 目标：

1. 引入“最新帧覆盖”队列语义，避免主线程逐包处理。
2. 合并重复解析流程，减少 Python 层对象创建。
3. 明确背压策略：可丢旧包，不可阻塞最新包。

`miframes` 目标：

1. 预分配结果容器，减少临时对象。
2. 热路径中减少字符串归一化重复计算。
3. 避免重复字典查询与 Python C API 往返。

完成判定：

1. 功能一致性测试全绿。
2. 指标相对 baseline 有明确提升。

## 阶段 P2：结构级优化

`face_cap` 目标：

1. 新增 native 运行时接口（建议）：
   - `start_receiver(host, port, options)`
   - `stop_receiver()`
   - `poll_latest_packet()`
   - `get_receiver_stats()`
2. Python runtime 退化为“控制器 + 定时消费器”。

`miframes` 目标：

1. 设计批量输入接口，减少 Python dict/list 深层嵌套。
2. 将高频映射与查表结构转换为更紧凑的 native 缓存布局。

完成判定：

1. 对外 service 合约不破坏。
2. 性能达到或接近目标线。

## 阶段 P3：深度优化与稳定性

优化方向：

1. SIMD（可选）。
2. 内存池与对象复用。
3. 锁粒度优化与无锁队列（仅在必要时引入）。
4. 长稳压测与异常注入（断连、脏包、突发流量）。

完成判定：

1. 长稳测试通过。
2. 无新增崩溃与明显行为回退。

---

## 6. face_cap 专项任务清单（用于独立会话）

## F0 基线任务

1. 建立本地压测发送器（JSON + Binary 两协议）。
2. 记录当前 `runtime.py` 路径的吞吐、延迟、CPU。
3. 输出 `face_cap_baseline.md`。

## F1 快速收益任务

1. 在 Python runtime 中明确“只保留最新包”的覆盖策略。
2. 收包批处理与主线程消费解耦。
3. 清理重复解析与重复编码判断。

## F2 Native 接收器任务

1. 在 `rig2_face_cap` 增加接收器生命周期 API。
2. 将握手、帧读取、解码、schema 解析尽可能留在 native。
3. Python 端改为周期性 `poll_latest_packet`。

## F3 稳定性任务

1. 异常输入测试：坏帧、半包、大包、异常断开。
2. 长连接压测：持续 30 分钟以上。
3. 输出 `face_cap_after.md` 与对比图表。

face_cap 验收阈值（建议）：

1. 吞吐 >= baseline 2x。
2. p99 延迟 <= baseline 70%。
3. 无崩溃、无线程泄漏。

---

## 7. miframes 专项任务清单（用于独立会话）

## M0 基线任务

1. 固定 `.miframes/.miobject` fixture 集。
2. 记录 `plan_miframes_keyframe_ops` 的耗时分布。
3. 输出 `miframes_baseline.md`。

## M1 热路径优化任务

1. 缓存高频字符串归一化结果。
2. 减少重复 `PyDict_GetItem*` 调用。
3. 预估并预分配 `operations/transitions` 容器容量。

## M2 接口优化任务

1. 新增批量/紧凑输入接口（保留旧接口）。
2. importer/service 按 feature flag 切换新旧路径。
3. 建立结果一致性对照（旧接口 vs 新接口）。

## M3 稳定性与边界任务

1. 极端 keyframe 数量测试。
2. 错误输入容错测试（缺字段、类型错）。
3. 输出 `miframes_after.md` 与对比图表。

miframes 验收阈值（建议）：

1. 平均耗时 <= baseline 75%。
2. p95 耗时明显下降。
3. 输出结果与旧路径一致（浮点阈值内）。

---

## 8. 测试与基准规范

统一要求：

1. 每项优化都要附 before/after 对比。
2. 每份报告必须包含：
   - 测试日期
   - commit hash
   - 机器配置
   - Python/Blender/编译参数
3. 关键路径新增测试后，CI 至少跑契约与一致性测试。

建议新增测试类型：

1. 合约测试：required symbols、API version。
2. 一致性测试：旧实现与新实现输出对齐。
3. 压测脚本：固定输入可重复执行。
4. 长稳测试：持续运行 + 资源监测。

---

## 9. 风险与回滚策略

主要风险：

1. native 接收线程与 Blender 主线程同步错误。
2. 协议边界条件引入行为回归。
3. 批量接口导致兼容性问题。

回滚原则：

1. 所有新路径受 feature flag 控制。
2. 任意阶段可一键切回旧路径。
3. 出现崩溃或数据错乱时优先回滚，再定位问题。

---

## 10. 会话执行模板（可直接复制到新对话）

### 模板 A：face_cap 会话

请按 `docs/CPP_PERFORMANCE_OPTIMIZATION_TASKS.md` 执行 `face_cap` 线任务，先完成 F0 基线，再做 F1。
要求：
1. 先提交 benchmark 与 baseline 报告。
2. 本次只改 `face_cap` 相关文件，不触碰 `miframes`。
3. 提交后给出 before/after 指标和回滚方式。

### 模板 B：miframes 会话

请按 `docs/CPP_PERFORMANCE_OPTIMIZATION_TASKS.md` 执行 `miframes` 线任务，先完成 M0 基线，再做 M1。
要求：
1. 先提交耗时基准与一致性测试。
2. 本次只改 `miframes` 相关文件，不触碰 `face_cap runtime`。
3. 提交后给出 before/after 指标和兼容性说明。

---

## 11. Definition of Done（最终完成条件）

1. `face_cap` 与 `miframes` 两条线均有完整 before/after 报告。
2. 关键指标达到目标或给出未达标原因与下一步计划。
3. 所有新增接口有契约测试，所有优化路径可回滚。
4. 用户可感知收益明确：更高吞吐、更低延迟、更稳运行。
