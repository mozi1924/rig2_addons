# Rig2 跨插件许可证接入说明

这份文档给 `mi2bl`、`r2bb` 这类强依赖 Rig2 的同级插件使用。目标是让它们只读取 Rig2 的授权状态，不重复接入 `orbisauth`，也不直接访问 Rig2 的 session 文件。

## 1. 适用前提

- `rig2_addons` 必须已安装。
- 运行时必须已经启用 Rig2 插件，让 `rig2_addons.src.licensing.register()` 完成初始化。
- 子插件把 Rig2 视为唯一 license provider，不做本地回退 provider。

如果导入成功但 Rig2 尚未启用，公共 API 会返回 `reason="provider_not_ready"`。

## 2. 允许依赖的公共入口

只使用下面这个导入路径：

```python
from rig2_addons.src.licensing.api import (
    FEATURE_FACE_CAP,
    FEATURE_MIFRAMES,
    get_feature_access,
    get_provider_status,
    is_feature_licensed,
)
```

当前公开的 feature 常量只有：

- `FEATURE_FACE_CAP`
- `FEATURE_MIFRAMES`

如果未来 Rig2 新增商业功能，必须先在这个公共模块和本文档里声明，子插件才可以依赖。

## 3. 返回字段契约

### `get_provider_status() -> dict`

固定返回这些字段：

- `provider_available`
- `provider_ready`
- `activated`
- `product`
- `tier`
- `features`
- `warnings`
- `reason`

其中：

- `provider_available` 表示 Rig2 授权层是否存在且可导入。
- `provider_ready` 表示 Rig2 插件是否已完成注册，授权运行时可安全读取。
- `features` 是一个 `dict[str, bool]`，只在 `activated=True` 时作为可用 feature 快照使用。
- `warnings` 是 primitives-only 的列表，可用于展示提示文案，但不要依赖其内部结构做业务分支。

### `get_feature_access(feature_name) -> dict`

固定返回这些字段：

- `feature`
- `available`
- `activated`
- `licensed`
- `reason`
- `message`

建议子插件只把它当作最终 gate 结果：

- `available=True` 才允许继续调用受保护能力
- `message` 直接用于用户提示
- `reason` 用于分支处理或埋点

### `is_feature_licensed(feature_name) -> bool`

这是 `get_feature_access(...)[\"licensed\"]` 的便捷封装。适合简单 `poll()` 或布尔判断，但如果你需要给用户展示失败原因，优先使用 `get_feature_access()`。

## 4. `reason` 枚举

首版只允许以下取值：

- `ok`
- `provider_missing`
- `provider_not_ready`
- `unactivated`
- `unlicensed`
- `session_error`
- `internal_error`

推荐处理方式：

- `ok`
  正常继续。
- `provider_missing`
  提示用户安装 Rig2。
- `provider_not_ready`
  提示用户启用 Rig2 插件。
- `unactivated`
  提示用户去 Rig2 Preferences 激活许可证。
- `unlicensed`
  提示当前 license tier 不包含该功能。
- `session_error`
  提示用户去 Rig2 Preferences 重新激活或执行同步。
- `internal_error`
  提示无法读取 Rig2 授权状态，并建议查看 Rig2 日志。

## 5. 推荐调用方式

### UI `poll()` 或按钮启用态

```python
from rig2_addons.src.licensing.api import FEATURE_MIFRAMES, is_feature_licensed


def can_use_miframes():
    return is_feature_licensed(FEATURE_MIFRAMES)
```

### Operator 执行前做最终检查

```python
from rig2_addons.src.licensing.api import FEATURE_MIFRAMES, get_feature_access


def ensure_miframes_access(operator):
    access = get_feature_access(FEATURE_MIFRAMES)
    if access["available"]:
        return True

    operator.report({"ERROR"}, access["message"])
    return False
```

### 区分“没装 Rig2”和“Rig2 没启用”

```python
from rig2_addons.src.licensing.api import get_provider_status


status = get_provider_status()
if status["reason"] == "provider_missing":
    # 提示安装 Rig2
    ...
elif status["reason"] == "provider_not_ready":
    # 提示启用 Rig2
    ...
```

## 6. 禁止事项

不要从子插件直接依赖这些内部实现：

- `rig2_addons.src.licensing.manager`
- `rig2_addons.src.licensing.feature_access`
- `rig2_addons.src.orbisauth`
- `rig2_addons.src.licensing.paths`
- session JSON 文件本身

也不要让子插件自己处理以下动作：

- license 激活 / 反激活
- 设备列表或设备解绑
- native binary 下载
- heartbeat / refresh 调度

这些动作全部保留在 Rig2 内部，由 Rig2 Preferences 和内部 licensing runtime 统一处理。
