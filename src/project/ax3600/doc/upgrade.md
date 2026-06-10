# AX3600 官方 API 刷固件 — `4.official_upgrade.py`

## 概述

通过小米 stock HTTP API 上传并刷写固件。**升级/降级通用**，每次刷写都清空 NVRAM 配置。
全程不需要 SSH，单机直连即可。

| 项 | 值 |
|----|----|
| 适用 | AX3600 (R3600) — IPQ8071A，工厂态和已初始化都能用 |
| 前置 | 一个有效的 `stok`（步骤 2 输出）|
| 后置 | 路由器自动重启，新固件上线，`inited=0`（NVRAM 已清）|
| 耗时 | 上传 ~30s + 路由器重启 ~45s = 总 ~75s |
| 网络 | 单机直连 192.168.31.1 |
| 失败回退 | 无（必须重置重试）|

## 用法

```bash
# 必传两参：--stok 和 --file
python3 4.official_upgrade.py --stok <token> --file files/R3600_1.0.17.bin

# 走管道（推荐，与项目其他 step 风格一致）
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/R3600_1.0.17.bin

# 直接刷 OpenWrt (custom=1 允许非官方固件)
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi

# 调试
python3 4.official_upgrade.py --stok <token> --file files/R3600_1.0.17.bin --debug
```

## 参数

| 参数 | 必传 | 默认 | 说明 |
|------|------|------|------|
| `--stok` | 否\* | `""` | 登录令牌；空则从 stdin 读上游 JSON |
| `--file` | ✅ | — | 固件文件路径（相对/绝对均可）|
| `--ip` | 否 | `192.168.31.1` | 路由器 IP |
| `--debug` | 否 | `False` | 打印进度日志到 stderr |

\* `--stok` 跟 stdin 二选一：显式传则用参数的，为空则尝试读 stdin。

## 输出

**成功** (stdout)
```json
{"ok": true, "step": "official_upgrade", "data": {
  "ip": "192.168.31.1",
  "firmware": "files/R3600_1.0.17.bin",
  "size_bytes": 28312508,
  "will_reboot": true
}}
```

**失败** (stdout)
```json
{"ok": false, "step": "official_upgrade", "error": "上传固件被拒 (code=1523): {...}"}
```

## 内部流程（4 步 API 链）

| 步骤 | 端点 | 关键参数 | 失败信号 |
|------|------|---------|---------|
| 1. 上传 | `POST /uploadfile/.../api/xqsystem/upload_rom` | multipart `image` 字段 | `code != 0`（如 1523 参数错误）|
| 2. 拿刷机锁 | `GET /web/syslock` | `flashtype=upload&downgrade=1` | HTTP ≠ 200 |
| 3. 刷机许可 | `GET /api/xqsystem/flash_permission` | — | `code != 0` |
| 4. 触发刷写 | `GET /api/xqsystem/flash_rom` | `custom=1&recovery=1` | `code != 0` |

> Step 4 返回成功时路由器**立即重启**，本脚本不等重启完成即 exit 0。

### 4 步链路的语义

每一步都是独立 HTTP 调用：

1. **upload_rom**：把固件字节流塞进路由器临时存储，路由器会先校验固件头（合法小米格式、固件 size 合理等）
2. **syslock**：上锁固件区，避免刷写过程中被并发操作打断；返回 200 表示锁成功
3. **flash_permission**：再次校验固件元信息是否与路由器硬件匹配（型号、版本号、签名等）
4. **flash_rom**：真正把临时存储的固件写进 flash；返回成功即触发重启

任何一步失败都说明前置条件不满足（stok 过期 / 固件不匹配 / 硬件不兼容），需要重置或换固件。

## 关键参数语义

### `syslock?downgrade=1` —— 永远带

不管升级还是降级都加 `downgrade=1`：

- **降级场景**：小米固件默认禁止"新版本覆盖旧版本"，加 `downgrade=1` 绕过版本检查
- **升级场景**：`downgrade=1` 是"放行版本检查"的双向开关，加了不影响升新版
- **好处**：脚本不需要知道方向（升/降），调用方决定

> 来源：用户明确要求"不管怎么样也带上downgrade标签吧"（2026-06-08）

### `flash_rom?recovery=1` —— 永远清 NVRAM

`recovery=1` 在刷写时同时清空 NVRAM（管理员密码、Wi-Fi 配置、stok、绑定状态等），
效果等同于"恢复出厂 + 刷入"。`inited=0` 是它的指纹。

> 来源：用户明确要求"升级或者降级都要带上清除配置文件的标签"（2026-06-08）

### `flash_rom?custom=1` —— 允许非官方固件

`custom=1` 放行非小米签名固件（uboot-mod、ImmortalWrt、OpenWrt 等）。
**不传的话只能刷小米官方包。**

> 这是脚本默认就带 `custom=1` 的原因 —— 刷机链路全栈可控。

## 实机验证

| 路由器 | 起始 FW | 目标 FW | 方向 | 验证日期 | 结果 |
|--------|--------|---------|------|---------|------|
| E0P534252 (Xiaomi_CFBB_3044) | 1.1.25 (工厂) | 1.0.17 | downgrade | 2026-06-09 | ✅ 28312508 bytes，romversion 切到 1.0.17，inited=0 |
| E0P534252 (Xiaomi_CFBB_3044) | 1.0.17 | OpenWrt (.ubi) | custom flash | 验证中（pipeline 内） | ⚠️ pipeline 实测中 |

> `recovery=1` 清 NVRAM 后 `inited=0`，重新跑 `1.official_init.py` 即可继续下一步。
> 整条链路 `2.login_get_stok.py → 4.official_upgrade.py` 在 1.1.x → 1.0.x 跨版本降级上行为一致。

### 验证标记

| 验证项 | 标记 |
|--------|------|
| `downgrade=1` 不影响降级流 | ✅ 实测 1.1.25 → 1.0.17 |
| `recovery=1` 真清 NVRAM | ✅ 降级后 `inited=0` |
| 4 步 API 链都返 `code:0` | ✅ 完整跑通 |
| 1.1.25 → 1.0.17 跨版本降级 | ✅ 实测 |
| 1.0.17 → 1.1.25 跨版本升级 | ⚠️ 未实测 |
| 1.0.x 系列内部升降 | ⚠️ 未实测 |
| 直接刷 OpenWrt (.ubi) | ⚠️ 待 pipeline 实测 |

## 常见错误码

| `error` 含 | 原因 | 解决 |
|------------|------|------|
| `上传固件被拒 (code=1523)` | 固件格式不识别 / 校验失败 | 检查固件是合法小米 `.bin`（不是 sysupgrade.tar）|
| `syslock 返回 HTTP 4xx` | stok 过期 | 重新跑步骤 2 |
| `刷机许可被拒 (code=...)` | 固件与硬件不匹配（型号 / region 错）| 换对应硬件版本的固件，**R3600 ≠ RA69** |
| `flash_rom 被拒` | 同上 / NVRAM 锁 | 路由器断电 30s 后重试 |

## 与 `old_coding/.../downgrade.py` 的关系

新脚本是 `old_coding/Auto_Flash_Router/AX3600/downgrade.py` 的精简+重构版本：

| | 旧 `downgrade.py` | 新 `4.official_upgrade.py` |
|---|---|---|
| 方向 | 仅降级（带 `downgrade=1`）| 升级/降级通用（永远带）|
| NVRAM | 不清（`recovery=0`）| 清（`recovery=1`）|
| 日志 | `print(json.dumps({"status":...}), stderr)` | 默静默 + `--debug` 开 |
| 错误处理 | 半成品（`{"error":...}` 形态不统一）| 统一 `RuntimeError` → `{"ok":false, "error":...}` |
| stdin 接管 | 不支持 | 支持（跟项目其他 step 一致）|

> **不保留** `old_coding/.../downgrade.py` 的代码，新脚本就是它的继任。

## 参考

- `old_coding/Auto_Flash_Router/AX3600/downgrade.py` — 原始 4 步链路实现
- `old_coding/router-flash/ax3600/downgrade.py` — 同一份实现的 router-flash 融合版
