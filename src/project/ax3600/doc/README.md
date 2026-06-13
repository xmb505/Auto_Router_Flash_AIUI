# AX3600 — 小米路由器 AX3600 (R3600)

## 目标设备

| 项目 | 值 |
|------|-----|
| 型号 | 小米路由器 AX3600 (R3600) |
| SoC | IPQ8071A (Qualcomm) |
| 默认 IP | `192.168.31.1` |
| 出厂密码 | `admin` |
| 加密 | `newEncryptMode=0` (SHA1) |
| 固件版本 | `1.0.17` / `1.1.25` 实测 |

> 与 **Redmi AX6 (RA69)** 同一 IPQ8071A 平台，但 SSH 注入链路不同：
> AX3600 走 `set_config_iotdev` 的 ssid 命令注入（仅旧版固件可用），
> AX6 走 smartcontroller + 时间操控（`enable-ssh-smartcontroller.md`）。
> **两者不可互换脚本**。

## 步骤脚本总览

| 编号 | 名称 | 状态 | 用途 | 文档 |
|------|------|------|------|------|
| 1 | `1.official_init.py` | ✅ | 出厂初始化向导 | [下面](#步骤-1官方初始化1official_initpy) |
| 2 | `2.login_get_stok.py` | ✅ | 登录获取 stok（KEY/加密模式运行时探测） | [下面](#步骤-2登录获取-stok2login_get_stokpy) |
| 3 | `3.enable_ssh.py` | ✅ | `set_config_iotdev` ssid 注入开 SSH（含 bdata + cron 自愈） | [`enable-ssh-iotdev.md`](enable-ssh-iotdev.md) |
| 4 | `4.official_upgrade.py` | ✅ | 官方 API 刷固件（升级/降级通用，清 NVRAM） | [`upgrade.md`](upgrade.md) |
| 5 | `5.firmware_upload_on_miwifi.sh` | ✅ | scp 上传到 /tmp（刷 OpenWrt 前置） | — |
| 6 | `6.miwifi_2_openwrt.py` | ✅ | ubiformat 烧镜像到非活跃 mtd（自动选对侧） | — |
| 7 | `7.custom_openwrt.py` | ✅ | 应用自定义 overlay 包 + 自动重启 | [`custom-openwrt.md`](custom-openwrt.md) |

> 工具脚本（不参与自动刷机顺序编号，单纯供人调试）:
> - `miwifi_ssh.sh` — SSH 复用组件（小米侧，含 ssh-rsa host key 兼容）
> - `get_router_info.sh` — 拉取并打印 `init_info`，无鉴权
> - `router_official_recovery.sh` — 官方 API 恢复出厂
> - `switch_to_stock.sh` — OpenWrt → 小米 stock 一键切回
> - `set_miwifi_uboot_partition.sh` — 3 个互补 nvram flag 切启动分区
> - `set_uboot_env.sh` — 批量设 nvram flags（默认 8 个 key）
> - `check_boot_partition.sh` — 探测当前活跃 mtd（依赖 cmdline，不靠 nvram）

## ⚠️ 关键约束：SSH 注入仅旧版固件可用

`set_config_iotdev` 的 ssid 参数注入漏洞在 **1.1.x 系列已被封堵**
（实测 1.1.25 连合法 SSID 都返 `code:1523 参数错误`）。

**当前可用路径**（按顺序）：

```
1.0.17 工厂态
  ├── 步骤 1: 1.official_init.py            ← 初始化设置密码
  │   ⚠️ 返回的 stok 改密后立即失效，丢弃
  ├── 步骤 2: 2.login_get_stok.py           ← 用新密码重新登录拿有效 stok
  ├── 步骤 3: 3.enable_ssh.py  ✅           ← 注入开 SSH (root/root)
  └── (可选) 步骤 4: 4.official_upgrade.py  ← 刷 LibWrt .ubi
```

```
1.1.x 工厂态 (set_config_iotdev 已封堵)
  ├── 步骤 4: 4.official_upgrade.py  ← 先降级到 1.0.17
  │   ⚠️ recovery=1 清 NVRAM, 路由器回到工厂态
  ├── 步骤 1: 1.official_init.py           ← 重新初始化（stok 立即失效）
  ├── 步骤 2: 2.login_get_stok.py           ← 用新密码重新登录拿新 stok
  └── 步骤 3: 3.enable_ssh.py  ✅
```

**⚠️ 关键提醒**：`1.official_init.py` 用旧密码 admin 登录拿 stok，改密后该 stok 立即失效。每次 init 后**必须**用 `2.login_get_stok.py` 重新登录拿新 stok。

实测验证：`26677/E0P534252` (1.1.25 → 1.0.17 → init → SSH 注入成功)

## 步骤 1：官方初始化（`1.official_init.py`）

工厂态路由器首次开 WEB 初始化。**运行时扒 KEY/IV，不写死任何密码学常量**。

```bash
python3 1.official_init.py --admin-pwd 12345678
```

### 输出

**成功** (stdout)
```json
{"ok": true, "step": "official_init", "data": {
  "stok": "abc123...",
  "ip": "192.168.31.1",
  "ssid": "Xiaomi_CFBB_3044",
  "firmware_version": "1.0.17"
}}
```

**失败** (stdout)
```json
{"ok": false, "step": "official_init", "error": "登录失败: {...}"}
```

### 内部流程

1. 扒 `init.html` 引用的 `init.<hash>.js` 拿 KEY/IV/newEncryptMode
2. 探测 `init_info` 读固件版本（决定 `bw160=false` 字段是否携带）
3. SHA1 双哈希登录（`newEncryptMode=0`）
4. 设 WAN = DHCP（POST `/api/xqnetwork/set_wan_new`）
5. 禁用自动更新（GET `/api/misystem/vas_switch`）
6. 设置 Wi-Fi + 管理密码（POST `/api/misystem/set_router_normal`）

> 密码学算法和 `bw160` 字段版本门控详见 [`init-login.md`](init-login.md)。

---

## 步骤 2：登录获取 stok（`2.login_get_stok.py`）

用于 stok 过期后的重新登录。**运行时扒 KEY 和 newEncryptMode**。

```bash
python3 2.login_get_stok.py --pwd 12345678
```

详见 [`init-login.md`](init-login.md) 中"步骤 2：登录获取 stok"章节。
AX3600 与 AX6 此步骤完全等价。

---

## 步骤 3：启用 SSH（`3.enable_ssh.py`）

通过 `set_config_iotdev` 的 ssid 参数注入命令开 SSH。详见 [`enable-ssh-iotdev.md`](enable-ssh-iotdev.md)。

```bash
# 拿 stok 后直接管道喂入
python3 2.login_get_stok.py --pwd 12345678 | python3 3.enable_ssh.py --wait

# 显式传
python3 3.enable_ssh.py --stok <token> --wait

# SSH 登录（dropbear 旧 host key 算法）
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 密码: root
```

---

## 步骤 4：官方 API 刷固件（`4.official_upgrade.py`）

通过 stock HTTP API 上传并刷写固件。**升级/降级通用**，都清 NVRAM。

```bash
# 降级到 1.0.17 (1.1.x 工厂态需要这步先开 SSH 路径)
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/R3600_1.0.17.bin

# 直接刷 OpenWrt (custom=1 允许非官方固件)
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
```

详见 [`upgrade.md`](upgrade.md)。关键约束：
- **必传** `--stok`（或上游 stdin）和 `--file`（固件路径）
- 路由器自动重启，`recovery=1` 同时清 NVRAM（刷完变 `inited=0`）
- 同一脚本同一参数列表处理升级/降级，**调用方决定方向**

---

## 实用工具

### `get_router_info.sh` — 无鉴权探针

```bash
./get_router_info.sh               # 默认 192.168.31.1
./get_router_info.sh --ip 192.168.1.1
```

拉 `init_info` 原始响应。快速判断：

| 字段 | 含义 |
|------|------|
| `inited` | `0`=工厂态, `1`=已初始化 |
| `romversion` | 固件版本 |
| `routername` | SSID |
| `bound` | 小米账号绑定状态 |
| `id` | SN，前缀 `26677/` 表示 AX3600 |
| `model` | `xiaomi.router.r3600` |

### `router_official_recovery.sh` — 一键恢复出厂

```bash
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['data']['stok'])")
./router_official_recovery.sh --stok "$STOK"
# ~45 秒后路由器回到 inited=0
```

详见 [`recovery.md`](recovery.md)。

### `switch_to_stock.sh` — 切到对侧分区

从当前系统切到对侧分区，无文件上传，仅 3 组 `fw_setenv` + reboot：

```bash
./switch_to_stock.sh                           # 默认 192.168.1.1
./switch_to_stock.sh --ip 192.168.1.1
# 重启后 IP 变到对侧分区所在系统
```

### `set_miwifi_uboot_partition.sh` — 切启动分区

3 个互补 nvram flag，决定下次启动从哪个 mtd 走：

```bash
./set_miwifi_uboot_partition.sh --part 0       # 切到 mtd12 (rootfs)
./set_miwifi_uboot_partition.sh --part 1       # 切到 mtd13 (rootfs_1)
```

### `set_uboot_env.sh` — 批量设 nvram flags

默认设 8 个推荐 key（ssh_en, telnet_en, uart_en, boot_wait 等）：

```bash
./set_uboot_env.sh                             # stock 侧
./set_uboot_env.sh --ip 192.168.1.1            # OpenWrt 侧
```

### `check_boot_partition.sh` — 探测当前活跃 mtd

读取 `/proc/cmdline` 判断：`ubi.mtd=rootfs` = mtd12, `ubi.mtd=rootfs_1` = mtd13。

```bash
./check_boot_partition.sh                      # stock 侧
./check_boot_partition.sh --ip 192.168.1.1     # OpenWrt 侧
```

## 步骤 5：上传固件（`5.firmware_upload_on_miwifi.sh`）

scp 上传固件/UBI 文件到路由器 `/tmp/`。

```bash
./5.firmware_upload_on_miwifi.sh \
    --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
```

## 步骤 6：烧写镜像到非活跃 mtd（`6.miwifi_2_openwrt.py`）

SSH ubiformat 烧到对侧的 mtd（不传 `--part` 自动选）。**不切 flag、不 reboot**——那归 `set_miwifi_uboot_partition.sh`。

```bash
# 上传步前置
./5.firmware_upload_on_miwifi.sh --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
# 自动探测当前活跃 mtd 并选对侧（推荐）
python3 6.miwifi_2_openwrt.py --file-name libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
# 显式指定
python3 6.miwifi_2_openwrt.py --file-name libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi --part 1
```

## 步骤 7：应用自定义 overlay（`7.custom_openwrt.py`）

LibWrt 跑起来后，把个性化主题/配置铺到 `/overlay/upper/`。

```bash
python3 7.custom_openwrt.py --file files/overlay-ax3600-new.tar.gz
```

详见 [`custom-openwrt.md`](custom-openwrt.md)。

---

## 依赖

- Python 3
- `pycryptodome`（`pip install pycryptodome`，仅步骤 1 需 AES-CBC）
- 路由器在同一二层网络可达
- SSH 客户端（步骤 3 之后）+ `sshpass`（脚本自动化场景）

## 资源

`files/` 目录放固件与资源：

| 文件 | 用途 |
|------|------|
| `R3600_1.0.17.bin` | 降级目标固件（set_config_iotdev 注入可用版本，28MB）|
| `libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi` | ⭐ **目标固件** LibWrt factory UBI（27MB，SSH: root / admin）|
| `overlay-ax3600-new.tar.gz` | 主题/配置 overlay 包（从 AX6 搬来，含 Argon 主题 + 中文翻译）|

## 密码学运行时探测

> **设计原则**：所有密码学常量都从路由器运行时扒取（前端 `init.<hash>.js`），
> 不在代码里写死。**不在文档/代码中固化任何 KEY/IV 字面值**——避免被误读为"写死常量"。

每次 init 都重新扒当前固件的 JS：

- 抓 `http://192.168.31.1/init.html` → 找到 `init.<hash>.js` 的引用
- 抓 `init.<hash>.js` → `grep -E "key\s*:\s*\"[0-9a-f]{32}\"|iv\s*:\s*\"[0-9a-f]{32}\""` 拿 key/iv
- 抓 `Encrypt.newEncryptMode` 字段决定 SHA1 / SHA256

新固件出现时**自动适配**——脚本不假设跨固件一致性，未实测的固件也按"先跑 `1.official_init.py` 看结果"处理；失败再 debug。

> 详细算法/字段语义见 [`init-login.md`](init-login.md)

---

## 文档索引

| 文档 | 主题 |
|------|------|
| [`init-login.md`](init-login.md) | 步骤 1 密码学流程、字段语义、bw160 版本门控 |
| [`enable-ssh-iotdev.md`](enable-ssh-iotdev.md) | 步骤 3 set_config_iotdev ssid 注入原理 + 版本限制 + bdata/cron 持久化 |
| [`upgrade.md`](upgrade.md) | 步骤 4 4 步 API 链、参数语义 |
| [`recovery.md`](recovery.md) | `router_official_recovery.sh` 一键重置用法 |
| [`custom-openwrt.md`](custom-openwrt.md) | 步骤 7 overlay 应用（主题/配置/预装包）|
| [`玩法说明书.md`](玩法说明书.md) | 全链路速查 + boot flag 原理 + 各路玩法 |