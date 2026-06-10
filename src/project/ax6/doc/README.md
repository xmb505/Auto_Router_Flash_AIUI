# AX6 — Redmi 路由器 AX6 (RA69)

## 目标设备

| 项目 | 值 |
|------|-----|
| 型号 | Redmi 路由器 AX6 (RA69) |
| SoC | IPQ8071A (Qualcomm) |
| 默认 IP | `192.168.31.1` |
| 出厂密码 | `admin` |
| 加密 | `newEncryptMode=0` (SHA1)，1.1.x 系列实测 |
| 固件版本 | `1.0.16` / `1.1.3` / `1.1.10` 均已实机验证 |

> AX6 是 **Redmi 版 AX3600**（同 IPQ807x 平台），但开 SSH 走的是
> smartcontroller 漏洞链路（`3.enable_ssh.py`），全程单机，**不需要辅助路由器**。
> 漏洞原理见 [`enable-ssh-smartcontroller.md`](enable-ssh-smartcontroller.md)。

## 步骤脚本总览

| 编号 | 名称 | 状态 | 用途 | 文档 |
|------|------|------|------|------|
| 1 | `1.official_init.py` | ✅ 已建 | 出厂初始化向导 | [下面](#步骤-1官方初始化1official_initpy) |
| 2 | `2.login_get_stok.py` | ✅ 已建 | 登录获取 stok（KEY/加密模式运行时探测）| [下面](#步骤-2登录获取-stok2login_get_stokpy) |
| 3 | `3.enable_ssh.py` | ✅ 已建 | smartcontroller 漏洞开 SSH | [`enable-ssh-smartcontroller.md`](enable-ssh-smartcontroller.md) |
| 4 | `4.official_upgrade.py` | ✅ 已建 | 官方 API 刷固件（升级/降级通用，清 NVRAM）| [`upgrade.md`](upgrade.md) |
| 5 | `5.firmware_upload_on_miwifi.sh` | ✅ 已建 | scp 上传固件到 `/tmp`（工具脚本） | — |
| 6 | `6.miwifi_2_openwrt.py` | ✅ 已建 | SSH ubiformat 烧镜像到非活跃 mtd（自动选对侧） | — |
| 7 | `7.custom_openwrt.py` | ✅ 已建 | 应用自定义 OpenWrt overlay 包 + 自动重启 | [`custom-openwrt.md`](custom-openwrt.md) |

> 工具脚本（不参与自动刷机，单纯供人调试）:
> - `get_router_info.sh` — 拉取并打印 `init_info`，无鉴权
> - `miwifi_ssh.sh` — SSH 复用组件（小米侧的 SSH 工具都通过它，**步骤 7 不复用**）
> - `set_uboot_env.sh` — 批量设 nvram flags（默认 8 个 / 自定义 `--set`）
> - `set_miwifi_uboot_partition.sh` — 单纯切启动分区（3 个互补 flag）
> - `check_boot_partition.sh` — 检测当前启动分区（不靠 nvram 判）
> - `router_official_recovery.sh` — 官方 API 恢复出厂
> - `switch_to_stock.sh` — OpenWrt → 小米 stock（`fw_setenv` + reboot）

---

## 完整流水线（一键命令）

从工厂态到 SSH 通 + nvram 全部设好的**端到端**流程，详见 [`flash-pipeline.md`](flash-pipeline.md)：

```
阶段 0: recovery         ← router_official_recovery.sh        （可选）
阶段 1: init             ← 1.official_init.py
阶段 2: 拿 stok         ← 2.login_get_stok.py
阶段 3: enable_ssh       ← 3.enable_ssh.py
阶段 4: set_uboot_env    ← set_uboot_env.sh
```

实测 1.0.16 全过（2026-06-09）。

## 步骤 1：官方初始化（`1.official_init.py`）

工厂态路由器首次开 WEB 初始化。**运行时扒 KEY/IV，不写死任何密码学常量**。

```bash
# 最常用：只传 admin-pwd，Wi-Fi 密码自动用同一个
python3 1.official_init.py --admin-pwd 12345678

# 自定义 SSID + 不同 Wi-Fi 密码
python3 1.official_init.py \
    --ssid My_AX6 \
    --wifi-pwd wifipass123 \
    --admin-pwd adminpass123

# 链式调用（喂给下一步）—— 默认静默，只有 JSON
python3 1.official_init.py --admin-pwd 12345678 | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['data']['stok'])"

# 调试：看中间过程
python3 1.official_init.py --debug --admin-pwd 12345678
```

### 输出

**成功** (stdout)
```json
{"ok": true, "step": "official_init", "data": {
  "stok": "abc123...",
  "ip": "192.168.31.1",
  "ssid": "Xiaomi_20A4",
  "firmware_version": "1.0.16"
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

用于 stok 过期后的重新登录，或在已初始化路由器上**单独**获取新 stok。
**运行时扒 KEY 和 newEncryptMode**，不假设任何加密模式。

```bash
# 最快路径：全用默认（IP 192.168.31.1 + 密码 12345678）
python3 2.login_get_stok.py --pwd 12345678

# 显式覆盖 IP
python3 2.login_get_stok.py --ip 192.168.31.1 --pwd adminpass123

# 链式喂给下一步
python3 2.login_get_stok.py --pwd 12345678 | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['data']['stok'])"

# 调试
python3 2.login_get_stok.py --pwd 12345678 --debug
```

### 输出

**成功** (stdout)
```json
{"ok": true, "step": "login_get_stok", "data": {
  "stok": "abc123...",
  "ip": "192.168.31.1",
  "encrypt_mode": 0,
  "key_source": "fetched from init.<hash>.js"
}}
```

### 内部流程

1. 扒 `init.<hash>.js` 拿 KEY 和 `newEncryptMode`
2. 探测 `init_info` 确认**已初始化**状态（`inited=1`）—— 工厂态会拒绝
3. 按 mode 选 SHA1 / SHA256 哈希算法，登录获取 stok

### 与步骤 1 的区别

| | 步骤 1（首次）| 步骤 2（已初始化）|
|---|---|---|
| `init_info.inited` | `0`（工厂）| `1`（已设置）|
| 登录 URL 的 `init=` | `1` | `0` |
| 改管理密码 | ✅（脚本替你改）| ❌（只读，不动）|
| 改 Wi-Fi | ✅ | ❌ |

> ⚠️ 步骤 1 的 `&init=1` 登录会被已初始化路由器拒绝（`code=401` "not auth"），
> 步骤 2 的 `&init=0` 登录会被工厂路由器拒绝。两者**不可互换**。

---

## 步骤 3：启用 SSH（`3.enable_ssh.py`）

通过 smartcontroller 漏洞（CVE-2023-26319）开 SSH，**单机直连，零物理外设**。

详见 [`enable-ssh-smartcontroller.md`](enable-ssh-smartcontroller.md)。关键点：

```bash
# 拿 stok 后直接管道喂入
python3 2.login_get_stok.py --pwd 12345678 | python3 3.enable_ssh.py

# 显式传
python3 3.enable_ssh.py --stok <token> --debug

# SSH 登录（dropbear 旧 host key 算法）
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 密码: root
```

---

## 步骤 4：官方 API 刷固件（`4.official_upgrade.py`）

通过 stock HTTP API 上传并刷写固件。**升级/降级通用**，都清 NVRAM。

```bash
# 升级示例: 1.0.16 → 1.1.3
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/RA69_1.1.3.bin

# 降级示例: 1.1.3 → 1.0.16
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/RA69_1.0.16.bin

# 调试
python3 4.official_upgrade.py --stok <token> --file files/RA69_1.1.3.bin --debug
```

详见 [`upgrade.md`](upgrade.md)。关键约束：
- **必传** `--stok`（或上游 stdin）和 `--file`（固件路径）
- 路由器自动重启，`recovery=1` 同时清 NVRAM（刷完变 `inited=0`）
- 同一脚本同一参数列表处理升级/降级，**调用方决定方向**

---

## 步骤 7：应用自定义 overlay（`7.custom_openwrt.py`）

OpenWrt 已跑起来后，上传一个 `.tar.gz` overlay 包到 `/overlay/upper/`，
自动重启后生效（主题、配置、预装包等一次性铺好）。

```bash
# 默认 (OpenWrt 192.168.1.1 + 免密)
python3 7.custom_openwrt.py --file files/overlay-new.tar.gz

# 显式 IP / 自定义 SSH 密码
python3 7.custom_openwrt.py --ip 192.168.1.1 --ssh-pwd mypass --file my.tar.gz

# 调试
python3 7.custom_openwrt.py --file files/overlay-new.tar.gz --debug
```

详见 [`custom-openwrt.md`](custom-openwrt.md)。要点：
- 走原生 `sshpass + scp/ssh`，**不复用**小米的 `miwifi_ssh.sh`（OpenWrt host key 是 ED25519，免密）
- 包结构必须是顶层 `overlay/` 目录（`tar -czf ... -C dir overlay`）
- 完成后自动 `reboot`，连接中断是预期，不算错

---

## 实用工具

### `get_router_info.sh` — 无鉴权探针

```bash
./get_router_info.sh                  # 默认 192.168.31.1
./get_router_info.sh --ip 192.168.1.1
```

拉 `init_info` 原始响应。快速判断：

| 字段 | 含义 |
|------|------|
| `inited` | `0`=工厂态, `1`=已初始化 |
| `romversion` | 固件版本 |
| `routername` | SSID（出厂态直接是 Wi-Fi 名）|
| `bound` | 小米账号绑定状态 |

### `router_official_recovery.sh` — 一键恢复出厂

```bash
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['data']['stok'])")
./router_official_recovery.sh --stok "$STOK"
# 约 45 秒后路由器回到 inited=0
```

详见 [`recovery.md`](recovery.md)。

---

## 依赖

- Python 3
- `pycryptodome`（`pip install pycryptodome`，仅步骤 1 需 AES-CBC）
- 路由器在同一二层网络可达
- SSH 客户端（步骤 3 之后）+ `sshpass`（脚本自动化场景）

## 资源

`files/` 目录放固件：

| 文件 | 用途 |
|------|------|
| `RA69_1.0.16.bin` | 降级目标固件（用于 SSH 链路兼容性测试等场景）|
| `RA69_1.1.3.bin` | 中间固件版本（步骤 4 实机验证用）|

## 密码学运行时探测

> **设计原则**：所有密码学常量都从路由器运行时扒取（前端 `init.<hash>.js`），
> 不在代码里写死。**不在文档/代码中固化任何 KEY/IV 字面值**——避免被误读为"写死常量"。

每次 init 都重新扒当前固件的 JS：

- 抓 `http://192.168.31.1/init.html` → 找到 `init.<hash>.js` 的引用
- 抓 `init.<hash>.js` → `grep -E "key\s*:\s*\"[0-9a-f]{32}\"|iv\s*:\s*\"[0-9a-f]{32}\""` 拿 key/iv
- 抓 `Encrypt.newEncryptMode` 字段决定 SHA1 / SHA256

新固件出现时**自动适配**——脚本不假设跨固件一致性，未实测的固件也按"先跑 `1.official_init.py` 看结果"处理；失败再 debug。

> 详细算法/字段语义见 [`init-login.md`](init-login.md)

### 登录哈希（参考，脚本实现不硬编码）

```python
inner    = SHA1(admin_pwd + KEY)             # SHA1 hex
password = SHA1(nonce + inner)               # SHA1 hex
```

### newPwd AES-CBC（参考）

```python
aes_key = SHA1(old_pwd + KEY)[:32]           # 16 bytes hex
plain   = SHA1(new_pwd + KEY).encode("utf-8")
newPwd  = AES_CBC_encrypt(plain, aes_key, IV, PKCS7)  # base64
```

nonce 格式：`0__{秒级时间戳}_{随机0-9999}`

---

## 完整流水线（参考）

典型场景：从 1.1.10 工厂态刷到 1.0.16（兼容老 SSH 链路）。

```bash
# === 阶段 1: 拿到登录权限 ===
python3 1.official_init.py --admin-pwd 12345678     # 工厂态初始化
python3 2.login_get_stok.py --pwd 12345678           # 拿 stok

# === 阶段 2:（可选）刷固件到目标版本 ===
python3 4.official_upgrade.py --file files/RA69_1.0.16.bin
# 等待重启 ~45 秒，重新初始化+登录
python3 1.official_init.py --admin-pwd 12345678
python3 2.login_get_stok.py --pwd 12345678

# === 阶段 3: 开 SSH ===
python3 3.enable_ssh.py
# 等 ~30 秒，TCP 22 就绪

# === 阶段 4: SSH 登录，root/root ===
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

> `4.official_upgrade.py` 和 `3.enable_ssh.py` 是**两条独立路径**：
> - 想刷固件 → 步骤 4（清 NVRAM 重新初始化）
> - 想保留当前固件但要 SSH → 步骤 3（不动 NVRAM，单纯开 SSH）
> - 想先刷再开 SSH → 串起来，按上面流水线

## 文档索引

| 文档 | 主题 |
|------|------|
| [`init-login.md`](init-login.md) | 步骤 1 密码学流程、字段语义、bw160 版本门控 |
| [`enable-ssh-smartcontroller.md`](enable-ssh-smartcontroller.md) | 步骤 3 漏洞原理、hackCheck 探测、注入细节 |
| [`upgrade.md`](upgrade.md) | 步骤 4 4 步 API 链、参数语义、双向刷机测试记录 |
| [`recovery.md`](recovery.md) | `router_official_recovery.sh` 一键重置用法 |
| [`custom-openwrt.md`](custom-openwrt.md) | 步骤 7 应用自定义 OpenWrt overlay + 自动重启 |
| [`switch-to-stock.md`](switch-to-stock.md) | `switch_to_stock.sh` OpenWrt → 小米 stock |
