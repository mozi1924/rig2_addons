# Orbisauth 与 R2 维护备忘

这份文档是给未来的自己看的，主要记录 Rig2 当前商业能力的几条关键链路：

- Orbisauth 负责许可证激活、JWT 校验、心跳续期、下载授权。
- Cloudflare R2 负责存放跨平台原生二进制，供 Orbisauth 下发临时下载链接。
- Blender 插件本地只做“二进制是否存在 + 许可证是否允许”两层 gate，不直接把业务逻辑写在 Python 里。

如果以后要改许可证、换桶、排查“功能锁住了”的问题，先看这份文档。

## 1. 当前实现在哪里

核心文件：

- `src/licensing/config.py`
  - 默认许可证服务地址：`https://orbisauth.mozi1924.com`
  - 产品 ID：`rig2`
  - 功能位：`face_cap`、`miframes`
- `src/licensing/manager.py`
  - `LicenseManager` 统一管理激活、状态、心跳、下载请求
- `src/licensing/__init__.py`
  - 插件注册时初始化 `LicenseManager`
  - 启动 Blender timer，每 `300s` 做一次 heartbeat
- `src/licensing/api.py`
  - 提供给 `mi2bl` / `r2bb` 这类同级插件使用的只读公共授权 API
  - 对外只暴露 primitives-only 状态，不暴露 `LicenseManager` / `orbisauth`
- `src/orbisauth/`
  - 内置的零依赖 Python SDK
  - 封装了 activate / refresh / heartbeat / download / JWT verify
- `src/native/loader.py`
  - 负责按平台 tag 查找本地原生库
- `src/services/face_cap_service.py`
- `src/services/miframes_service.py`
  - 最终对外的功能 gate：原生库存在 + license feature 命中
- `scripts/build_native.py`
  - 本地构建原生扩展并复制到运行时目录
- `scripts/extract_native_from_wheels.py`
  - 从 CI 产出的 wheel 提取运行时原生库
- `scripts/upload_to_r2.py`
  - 上传原生二进制到 Cloudflare R2
- `.github/workflows/build-native-binaries.yml`
  - CI 构建 wheel、提取原生库、上传到 R2

## 2. 许可证链路现在是怎么走的

### 2.1 插件启动

`src/__init__.py` 注册模块时会带上 `src/licensing/__init__.py`。

`licensing.register()` 会做两件事：

1. 调 `get_license_manager()`，尽量加载本地已有 session。
2. 注册 Blender timer，按 `HEARTBEAT_INTERVAL_SECONDS=300` 秒定期 heartbeat。

所以许可证系统是插件加载即初始化，不是等用户点按钮时才初始化。

### 2.1.1 跨插件授权架构

Rig2 现在同时承担“商业功能宿主”和“唯一 license provider”两个角色：

- `rig2_addons` 自己内部继续直接使用 `src/licensing/manager.py`、`feature_access.py`
- 同级依赖插件只允许走 `src/licensing/api.py`
- 公共 API 只提供只读授权状态，不提供激活、下载、session 路径或 heartbeat 控制

这样做的目的是确保：

- Orbisauth 仍然只接一次
- session 文件仍然只有一份
- 未来 `mi2bl` / `r2bb` 不会各自复制一套许可证实现

如果后续增加新的商业 feature，先更新：

1. `src/licensing/config.py` 中的 feature 常量
2. `src/licensing/api.py` 的公共暴露范围
3. `docs/licensing/CROSS_ADDON_INTEGRATION.md`

然后再允许外部插件依赖这个新 feature。

### 2.2 激活

Blender 偏好设置界面在 `src/preferences.py`。

用户点击 `Activate` 后，调用的是：

- `RIG2_OT_activate_license.execute()`
- `LicenseManager.activate()`
- `OrbisAuthClient.activate()`
- `POST {server_url}/api/v1/activate`

激活成功后，本地会保存一个 session JSON，里面包含：

- access token
- refresh token
- product / tier
- feature flags
- heartbeat policy
- device_id / device_name

### 2.3 Session 文件保存在哪里

路径逻辑在 `src/licensing/paths.py`：

- 优先使用 `RIG2_SESSION_DIR`
- 如果在 Blender 内可拿到用户配置目录，则优先写到 Blender 用户侧的 `rig2_addons`
- 否则写到平台用户状态目录
- 如果这些目录都不可写，再 fallback 到 `RIG2_NATIVE_ROOT` 或 `src/native/binaries`
- 最后才 fallback 到系统临时目录 `rig2_addons`

session 文件名固定为：

- `rig2_license_session.json`

这意味着现在默认更安全：

- 用户许可证状态优先和源码目录分开
- 清理 addon 工作区时，不再默认把 session 一起清掉
- 只有在用户状态目录不可写时，session 才会回退到 addon runtime 目录

### 2.4 功能解锁条件

真正控制商业功能是否可用的逻辑不在 UI，而在 service 层：

- `FaceCapBackendService.is_feature_unlocked()`
- `MiframesBackendService.is_feature_unlocked()`

都要求同时满足：

1. 对应 native backend 已成功加载
2. 当前 license session 有对应 feature flag

也就是说，以下任一情况都会表现成“功能锁住”：

- 本地没有对应平台的原生库
- 原生库 API 版本不匹配
- license 未激活
- token 失效
- 当前 tier 不包含该 feature

排查时不要只盯着许可证。

### 2.5 本地校验与心跳

`LicenseManager.is_feature_licensed()` 最终调用 `OrbisAuthClient.get_features()`。

这个步骤是：

- 本地校验 access token JWT
- 用 token 中的 `features` claim 做功能判断
- 正常情况下不需要实时请求服务端

服务端通信主要发生在这些动作：

- `activate`
- `refresh`
- `heartbeat`
- `request_download`
- `list_devices`

`heartbeat()` 失败目前是非致命的，代码里按 best-effort 处理。只要 token 还没真正过期，本地功能不一定立刻失效。

## 3. Device ID / Device Name 的来源

在 `src/licensing/manager.py`：

- `device_id`
  - 优先基于 `uuid.getnode()` 生成稳定 ID
  - 异常时退回随机 `uuid4`
- `device_name`
  - 形如 `hostname (OS)`

这意味着更换机器、网卡环境异常、或者底层硬件标识变化时，可能会被 Orbisauth 视为新设备。

如果以后出现“明明激活过但设备数满了”，先想到这个点。

## 4. 下载链路与 R2 的关系

### 4.1 设计意图

当前代码已经具备“按需下载原生库”的基础能力：

- `LicenseManager.request_download()`
- `LicenseManager.download_file()`
- `OrbisAuthClient.request_download()`
- `OrbisAuthClient.download_file()`

这里的职责分工应该是：

- Orbisauth 判断用户是否有权限下载某模块、某平台的产物
- Orbisauth 返回一个带时效的下载 URL + download token
- 真实文件落在 Cloudflare R2

目前仓库里我没有看到完整的“缺文件时自动下载并安装 native backend”的调用闭环，现阶段更像是服务端和客户端 SDK 已经准备好，但前端产品化流程还没全部接上。

换句话说：

- 下载 API 已有
- R2 上传流程已有
- 但插件运行时自动拉取原生库这一步，至少在当前仓库里还不是完整主路径

## 5. R2 目录结构约定

`scripts/upload_to_r2.py` 里写死了目标结构：

`{storage_prefix}/{module}/{platform}/{arch}/{artifact}`

当前 module 只有两个：

- `rig2_face_cap`
- `rig2_miframes`

当前平台映射如下：

- `darwin-x86_64-abi3` -> `mac/amd64/mac.dylib`
- `darwin-arm64-abi3` -> `mac/arm64/mac.dylib`
- `linux-x86_64-abi3` -> `linux/amd64/linux.so`
- `linux-arm64-abi3` -> `linux/arm64/linux.so`
- `win32-x86_64-abi3` -> `win/amd64/win.dll`
- `win32-arm64-abi3` -> `win/arm64/win.dll`

所以最终路径大概长这样：

```text
rig2/rig2_face_cap/mac/arm64/mac.dylib
rig2/rig2_face_cap/mac/amd64/mac.dylib
rig2/rig2_face_cap/linux/amd64/linux.so
rig2/rig2_face_cap/win/amd64/win.dll
rig2/rig2_miframes/mac/arm64/mac.dylib
...
```

这里最重要的约束是：

- `storage_prefix` 现在应当与产品 ID 保持一致，用的是 `rig2`
- module 名称必须和服务端下载授权时使用的 module 一致
- platform / arch / artifact 命名不要随便改，否则会和服务端或客户端约定断开

## 6. 本地构建、CI、R2 上传是怎么串起来的

### 6.1 本地构建

常用命令：

```bash
python3 scripts/build_native.py
```

默认尽量构建 ABI3 二进制，产物会复制到：

- `src/native/binaries/<sys.platform>-<arch>-abi3/`
- `src/native/binaries/<sys.platform>-abi3/`
- 以及兼容用的非 abi3 tag 目录

强制关闭 ABI3：

```bash
RIG2_ENABLE_ABI3=0 python3 scripts/build_native.py
```

### 6.2 运行时查找顺序

`src/native/loader.py` 的搜索顺序是：

1. `<sys.platform>-<arch>-abi3`
2. `<sys.platform>-abi3`
3. `<sys.platform>-<arch>-<pyver>`
4. `<sys.platform>-<pyver>`

所以如果你替换了某个平台的库，记得优先看 abi3 目录里的文件是不是旧的；很多“我明明换过库但没生效”就是因为 loader 先吃到了旧的 abi3 文件。

### 6.3 CI

`.github/workflows/build-native-binaries.yml` 当前分三段：

1. `build-wheels`
   - 用 `cibuildwheel` 构建 `cp39-*`
   - Linux: `x86_64`、`aarch64`
   - macOS: `x86_64`、`arm64`
   - Windows: `AMD64`、`ARM64`
2. `package-native`
   - 下载 wheel artifacts
   - 用 `scripts/extract_native_from_wheels.py` 提取到 `native_dist/`
3. `upload-r2`
   - 安装 `boto3`
   - 调 `scripts/upload_to_r2.py --binary-dir native_dist --storage-prefix rig2`

而且 `upload-r2` 只在非 PR 事件执行。

### 6.4 CI 依赖的 Secrets

R2 上传依赖这些环境变量/Secrets：

- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`

本地手动上传也同样依赖这些值。

## 7. 手动上传到 R2 的命令

先装依赖：

```bash
pip install boto3
```

然后执行：

```bash
python scripts/upload_to_r2.py \
  --binary-dir native_dist \
  --storage-prefix rig2
```

如果不想每次手填参数，至少要准备环境变量：

```bash
export R2_ENDPOINT_URL=...
export R2_ACCESS_KEY_ID=...
export R2_SECRET_ACCESS_KEY=...
export R2_BUCKET_NAME=...
```

脚本会遍历固定的平台 tag 目录，并尝试查找两个模块：

- `rig2_face_cap*`
- `rig2_miframes*`

如果目录不存在或者模块文件没找到，会打印 `skip`。

如果最后一个文件都没传上去，会直接报错：

- `No binaries were uploaded — check binary-dir contents`

## 8. 这块以后最容易踩的坑

### 8.1 清理原生库目录时误删 fallback session

现在 session 默认不再和 native binaries 放在一起，但如果用户状态目录不可写，仍可能 fallback 到 addon runtime 目录。
排查时先看 `src/licensing/paths.py` 最终选中了哪条路径。

### 8.2 改了 native API，但忘了同步版本号

当前版本号：

- `src/native/face_cap_wrapper.py`: `FACE_CAP_NATIVE_API_VERSION = 2`
- `src/native/miframes_wrapper.py`: `MIFRAMES_NATIVE_API_VERSION = 1`

如果 C++ 导出接口变了，但 wrapper 预期没改，结果就是加载失败，看起来像“功能锁住”。

### 8.3 只改了 wheel，没更新 runtime 提取/上传结果

仓库运行时实际吃的是：

- `src/native/binaries/...`

分发/下载时真正上传的是：

- CI 里从 wheel 提取后的 `native_dist/...`

不要混淆“wheel 能 build”与“插件能直接加载”。

### 8.4 R2 上文件名不是原始扩展名，而是统一 artifact 名

上传脚本不是保留原始文件名，而是重命名为：

- `mac.dylib`
- `linux.so`
- `win.dll`

以后如果服务端下载逻辑按原 wheel 文件名找，很可能对不上。现在这套约定明显是“服务端知道标准 artifact 名，不依赖原始编译文件名”。

### 8.5 loader 搜索顺序会让旧 abi3 产物抢先命中

这点非常常见，排查时优先打印：

- 当前平台 tag
- 实际命中的 `backend_path()`

不然会误以为“新库没编进去”。

### 8.6 当前 README 主要面向使用者，不是维护者

以前如果只看 `README.md`，很容易忽略：

- Orbisauth server 地址从哪里来
- feature flag 名称是什么
- R2 上传目录结构是什么
- CI 在哪里上传 R2

所以后续维护这一块，优先看本文件。

## 9. 建议保持不变的约定

除非服务端一起改，否则这些值最好不要轻易变：

- 产品 ID：`rig2`
- feature 名：`face_cap`、`miframes`
- module 名：`rig2_face_cap`、`rig2_miframes`
- R2 storage prefix：`rig2`
- artifact 名：`mac.dylib`、`linux.so`、`win.dll`

这些名字一旦有一处改了，常常会连锁影响：

- 客户端 feature gate
- 服务端 license payload
- 下载 API 参数
- R2 对象路径
- 自动化构建与上传

## 10. C++ 原生层许可执行

2026-05 起，两个原生模块内部加入了许可验证：

- `rig2_face_cap.cpp` (API v3) 和 `rig2_miframes.cpp` (API v2)
- 模块内嵌 32 字节共享密钥
- Python 层在激活/心跳后通过 `set_license_state(device_id, expires_at, hmac_proof)` 传递许可证明
- C++ 模块用 `hashlib.hmac` 验证 proof，验证通过才启用敏感函数
- 敏感函数入口处有 `CHECK_LICENSE()` 宏，未许可时抛出 `PermissionError`

### 10.1 如何轮换共享密钥

1. 生成新的 32 字节随机值
2. 更新 `src/licensing/registry.py` 中对应 feature spec 的 `shared_secret`
3. 更新对应 `.cpp` 文件中的 `kLicenseSecret[32]` 数组
4. 更新 `kExpectedPyHashes` 中的文件哈希（如果相关 .py 文件有改动）
5. 重新编译、重新上传到 R2

### 10.2 Python 文件完整性检查

- C++ 模块内嵌了关键 Python 文件的 SHA-256 期望值
- Python 启动时传入当前文件哈希到 `verify_integrity()`
- 哈希不匹配 → C++ 内部拒绝所有许可操作
- 覆盖文件：`face_cap_service.py`, `miframes_service.py`, `manager.py`
- 修改这些文件后**必须**重新计算哈希并更新 C++ 源码

### 10.3 设备 ID 来源

- macOS: `ioreg -rd1 -c IOPlatformExpertDevice` → IOPlatformUUID
- Linux: `/etc/machine-id` 或 `/var/lib/dbus/machine-id`
- Windows: `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography\MachineGuid`
- 所有平台回退: `bpy.utils.user_resource('CONFIG')/rig2_device_id`
- 不再使用 MAC 地址 (`uuid.getnode()`)

## 11. 建议以后补的事

1. 增加一份明确的”Orbisauth 服务端接口约定文档”
2. 给 `upload_to_r2.py` 增加 dry-run 或校验模式
3. 给 CI 增加上传后的对象存在性检查

## 12. 一句话总结
3. 把“按需下载原生库”的完整闭环真正接起来，而不只是保留 SDK 能力。
4. 给 `upload_to_r2.py` 增加 dry-run 或校验模式，上传前先列出将要写入的 key。
5. 给 CI 增加上传后的对象存在性检查，避免 Secrets 正常但路径写错时无人发现。

## 12. 一句话总结

这套系统目前的真实结构可以理解为：

- Orbisauth 决定”你有没有权限”
- 本地 native loader 决定”你有没有可加载的库”
- service 层决定”功能最终解不解锁”
- C++ 原生模块内部独立验证许可（防直接调用绕过）
- R2 只是二进制存储，不负责授权判断

以后遇到问题，按这个顺序排查，通常最快。
