---
name: ax6-stock-to-openwrt-pipeline
description: Redmi AX6 (RA69) 从小米 stock 固件刷到 ImmortalWrt/OpenWrt 的完整流水线——工具调用顺序、状态检查点、决策分支、验证方法
source: auto-skill
extracted_at: '2026-06-09T16:13:50.305Z'
---

# AX6 (RA69) stock → OpenWrt 批量刷机流水线

## 适用场景

有一个 **Redmi AX6 (RA69)** 路由器（SoC IPQ8071A），你手里有 `src/project/ax6/` 下全套工具脚本和 `.ubi` 固件文件，目标是把它从小米官方固件刷成 ImmortalWrt / OpenWrt。

**前置**：
- 路由器已在局域网（默认 IP `192.168.31.1`）
- 你的机器在该网段，可 curl/SSH 到路由器
- `sshpass` 已安装

## 流水线总览

```
[探针] get_router_info.sh  ── 检查 inited / romversion / bound
    │
    ├── inited=0 ──────────────────────→ 1.official_init.py
    ├── inited=1, 知道密码 ────────────→ 2.login_get_stok.py
    └── inited=1, 不知道密码 ──────────→ router_official_recovery.sh → 1.official_init.py
                                           │
    ┌──── SSH 开启后 ──────────────────┐
    ▼                                   ▼
3.enable_ssh.py                 4.official_upgrade.py (备选：刷 stock)
    │
    ▼
set_uboot_env.sh  ── 8 个 nvram flags
    │
    ▼
check_boot_partition.sh  ── 确定非活跃 mtd
    │
    ▼
5.firmware_upload_on_miwifi.sh  ── scp → /tmp/
    │
    ▼
6.miwifi_2_openwrt.py  ── ubiformat 烧非活跃 mtd
    │
    ▼
set_miwifi_uboot_partition.sh  ── 切启动分区
    │
    ▼
reboot  ── 路由器从 OpenWrt 启动
    │
    ▼
验证：ping 192.168.1.1 → curl LuCI → SSH 免密登录
```

## 步骤详解

### 阶段 0：探针

```bash
cd src/project/ax6
bash get_router_info.sh
```

**读什么**：

| 字段 | 含义 | 决策 |
|------|------|------|
| `inited` | `0`=工厂态, `1`=已初始化 | `0` → 直接步骤 1；`1` → 需要密码 |
| `romversion` | 当前固件版本 | 决定了 `bw160` 门控 |
| `bound` | `0`=未绑定账号 | 无需处理 |
| `routername` | 路由器 SSID | 记录（步骤 1 或 2 会用它当默认 SSID）|

**成功信号**：路由器可达，JSON 正常返回。

### 阶段 1：工厂初始化（inited=0）

```bash
python3 1.official_init.py --admin-pwd <你的密码>
```

**脚本干的事**（5 步）：
1. 扒 `init.html` → `init.<hash>.js` 提取 KEY/IV
2. 用出厂密码 `admin` + `init=1` 登录拿 stok
3. `set_wan_new`：设 WAN = DHCP
4. `vas_switch`：禁用自动更新
5. `set_router_normal`：设 Wi-Fi SSID + 密码 + 管理密码（AES-CBC 加密）

**关键注意**：
- `--admin-pwd` **required**（无默认值），这将成为后续所有步骤的密码
- `--wifi-pwd` 可选，不传时默认等于 `--admin-pwd`
- `--ssid` 可选，不传时从 `init_info.routername` 自动抓
- 固件 ≥ 1.1.x 自动加 `bw160=false` 字段
- **nonce 1582 重试**：post-recovery 首次运行时 `set_router_normal` 可能因 `nonce 1582` 失败（路由器侧状态问题）。重试 2-3 次即过。非脚本 bug。

**输出**：JSON with `data.stok`（可用于下一阶段）。

### 阶段 2：登录拿 stok（inited=1，知道密码）

如果路由器已是 `inited=1` 且你知道密码：

```bash
# 方式 A：从上一步管道
python3 1.official_init.py --admin-pwd 12345678 | python3 2.login_get_stok.py --pwd 12345678

# 方式 B：直接登录
python3 2.login_get_stok.py --pwd <密码>
```

**密钥决策**：自动从 JS 探测 `newEncryptMode`，SHA1（mode=0）或 SHA256（mode=1）。AX6 是 mode=0。

### 阶段 2b：恢复出厂（inited=1，不知道密码）

```bash
# 先拿 stok
python3 2.login_get_stok.py --pwd <已知密码>
                         # 或从上游管道
# 然后恢复
bash router_official_recovery.sh --stok <stok>
# 等待 ~45 秒，轮询直到 inited=0
# 然后回到阶段 1
```

**时序**：reset 请求返回后约 **45 秒**路由器重启完毕，不是文档写的 2-3 分钟（memory `project_ax6_reset_cycle_45s.md`）。

### 阶段 3：启用 SSH（CVE-2023-26319 智能场景注入）

```bash
# 方式 A：从上游管道传 stok
python3 2.login_get_stok.py --pwd 12345678 | python3 3.enable_ssh.py

# 方式 B：直接传 stok
python3 3.enable_ssh.py --stok <stok>
```

**内部流程**（详见 skill `ax6-smartcontroller-exploit`）：

1. hackCheck 探测（AX6 是 0=无过滤）
2. 保存原系统时间
3. 热身 smartcontroller（`set_sys_time` 触发 3s sleep 懒启动）
4. 32 秒循环注入 `date -s 203301020304` 验证链路
5. 恢复原时间
6. 注入 nvram SSH 开关 + 设 root 密码为 `root`
7. **关键**：`sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear` — **必须做**（所有 stock 固件都有 release 检查锁）
8. `dropbear enable` + `restart`
9. TCP 22 探测（最多 33 秒）
10. 清理 `/tmp/e /tmp/x`

**典型耗时**：约 35-40 秒（含 32 秒链路验证 + dropbear 启动）。

**输出**：SSH 已就绪，`root/root`，端口 22。

**验证**：
```bash
sshpass -p root ssh -o HostKeyAlgorithms=+ssh-rsa root@192.168.31.1 id
```

### 阶段 4：设 nvram flags

```bash
bash set_uboot_env.sh
```

自动设 8 个 key + commit + nvram get 验证回读。

**默认值**：

| Key | 值 | 作用 |
|-----|-----|------|
| `flag_last_success` | `0` | uboot 启动标志 |
| `flag_boot_success` | `1` | 启动成功 |
| `flag_try_sys1_failed` | `0` | sys1 失败计数 |
| `flag_try_sys2_failed` | `0` | sys2 失败计数 |
| `boot_wait` | `on` | uboot 等 tftp |
| `uart_en` | `1` | UART 调试口 |
| `telnet_en` | `1` | telnet 服务 |
| `ssh_en` | `1` | SSH 服务 |

**输出验证**：`verified` 字段的 8 个值与意图完全一致。

### 阶段 5：探测 mtd 布局

```bash
bash check_boot_partition.sh
```

**解读**：
- `current_partition: "rootfs"` + `current_mtd: "mtd12"` → 活跃是 mtd12
- `current_partition: "rootfs_1"` + `current_mtd: "mtd13"` → 活跃是 mtd13
- 非活跃的 mtd 是安全烧写目标

**关键原则**："哪个 mtd 是哪个系统"**不固定**，必须运行时探测。不要硬编码 mtd12=stock / mtd13=OpenWrt。

### 阶段 6：上传固件

```bash
# 选择要刷的 .ubi 文件
bash 5.firmware_upload_on_miwifi.sh --file files/immortalwrt-25.12.0-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi
```

文件传到 `/tmp/` 下同名。`-O` 参数绕过 sftp（旧 Dropbear 不支持）。

### 阶段 7：烧写镜像（自动选对侧，推荐）

```bash
# 自动探测当前活跃 mtd，选对侧（不传 --part 即可）
python3 6.miwifi_2_openwrt.py \
  --file-name immortalwrt-25.12.0-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi
```

**自动选对侧逻辑**：
不传 `--part` 时脚本自动：
1. SSH `cat /proc/cmdline` 解析 `ubi.mtd=rootfs`（mtd12）或 `ubi.mtd=rootfs_1`（mtd13）
2. 当前 mtd12 → 自动选 `part=1`(mtd13)，当前 mtd13 → 自动选 `part=0`(mtd12)

**安全检查**：
- `writing_to_inactive: true` 确认烧的是非活跃分区，安全
- 如活跃 mtd 探测失败（SSH 不通），脚本报错退出
- 如必须指定某个 mtd（例如 OpenWrt 里烧回 stock 到 mtd12），仍可传 `--part 0`

**关键意义**：解决了"万一活跃 mtd13 怎么办"的问题。无论当前从哪个分区启动，`--part` 不传就永远只烧对侧。

**输出验证**：
```json
{"writing_to_inactive": true, "safety_warning": null, ...}
```

**手动指定（不推荐，除非明确知道当前活跃分区）**：
```bash
# 不传 --part 更安全，以下仅作参考
python3 6.miwifi_2_openwrt.py --part 1 \
  --file-name immortalwrt-25.12.0-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi
```

### 阶段 8：切启动分区 + reboot

```bash
# 切到 mtd13（part=1）
bash set_miwifi_uboot_partition.sh --part 1

# reboot
bash miwifi_ssh.sh --cmd reboot
```

**3 个 flag 的互补逻辑**：

| `--part` | `flag_try_sys1_failed` | `flag_try_sys2_failed` | `flag_boot_rootfs` |
|----------|------------------------|------------------------|---------------------|
| 0 (mtd12) | 0 | 1 | 0 |
| 1 (mtd13) | 1 | 0 | 1 |

**关于 uboot env**：`nvram`（stock）/ `fw_setenv`（OpenWrt）/ UART `setenv` 三个工具读写**同一份 NAND env 分区**。不需要 UART 线——切分区全程软件可完成。

### 阶段 9：验证 OpenWrt 启动

reboot 后路由器会：
- IP 改为 **192.168.1.1**（OpenWrt 默认）
- 不再响应 192.168.31.1
- SSH 用 **ED25519 key**（不是 stock 的 RSA），**免密登录**（空密码）

```bash
# 1. ping 通
ping -c 3 192.168.1.1

# 2. LuCI web
curl -s http://192.168.1.1/cgi-bin/luci | grep '<title>'

# 3. SSH 免密登录
sshpass -p "" ssh -o StrictHostKeyChecking=no root@192.168.1.1 uname -a

# 4. 查看系统信息
sshpass -p "" ssh root@192.168.1.1 "cat /etc/openwrt_release; ubus call system board"
```

**典型 ImmortalWrt 输出**：

```
DISTRIB_ID='ImmortalWrt'
DISTRIB_RELEASE='25.12.0'
DISTRIB_TARGET='qualcommax/ipq807x'
Kernel: 6.12.87
Model: Redmi AX6 (stock layout)
Board: redmi,ax6-stock
```

## 双系统回退

刷完后 mtd12 仍是小米 stock 固件，mtd13 是 OpenWrt。两个方向来回切：

### 方向 A：OpenWrt → 小米 stock（在 OpenWrt 上执行）

OpenWrt 下没有 `nvram`，用 `fw_setenv` 写 uboot flag：

```bash
# 方式 1：一键脚本（推荐）
bash switch_to_stock.sh
# 输出: {"ok":true,"next_ip":"192.168.31.1"}
# 等 ~45s → stock 回到 192.168.31.1

# 方式 2：手动 SSH
ssh root@192.168.1.1
fw_setenv flag_try_sys1_failed 0
fw_setenv flag_boot_rootfs 0
reboot
```

**关键**：`fw_setenv` 和 stock 侧的 `nvram` 读写**同一份 NAND env 分区**（不是两份独立的 env）。切分区全程纯软件，不需要 UART 线。

### 方向 B：小米 stock → OpenWrt（在 stock 上执行）

```bash
bash set_miwifi_uboot_partition.sh --part 1
bash miwifi_ssh.sh --cmd reboot
# 路由器从 mtd13 启动（OpenWrt），回到 192.168.1.1
```

### 方向 C：任意状态 → 自动选对侧（推荐用于初始烧写）

使用 `6.miwifi_2_openwrt.py` 时不传 `--part`，脚本自动探测当前活跃 mtd 并选对侧烧写：

```bash
# 无论当前活跃是 mtd12 还是 mtd13，永远烧对侧
python3 6.miwifi_2_openwrt.py --file-name immortalwrt.ubi
```

**原理**：
1. SSH `cat /proc/cmdline` 解析 `ubi.mtd=rootfs`（mtd12）或 `ubi.mtd=rootfs_1`（mtd13）
2. 当前 mtd12 → 自动 `part=1`，当前 mtd13 → 自动 `part=0`
3. `writing_to_inactive: true` 确认安全

解决了"万一活跃是 mtd13 怎么办"的问题——永远不烧正在运行的系统。

### 状态检查

切完后随时用以下命令确认当前从哪个分区启动：

```bash
# stock 侧
bash check_boot_partition.sh

# OpenWrt 侧
cat /proc/cmdline | grep ubi.mtd
# ubi.mtd=rootfs → mtd12
# ubi.mtd=rootfs_1 → mtd13
```

## 实测验证记录

| 日期 | 固件 | 流程 | 结果 |
|------|------|------|------|
| 2026-06-09 | 1.1.10 → ImmortalWrt 25.12.0 | 全流水线（阶段 0-9） | ✅ 一次成功 |
| 2026-06-08 | 1.1.10 / 1.1.3 / 1.0.16 | 阶段 0-3（init→SSH） | ✅ 多版本验证 |
| 2026-06-08 | 1.1.10↔1.1.3↔1.0.16 | 阶段 0→1→2→stock 刷机（4.official_upgrade.py） | ✅ 双向验证 |

## 常见失败模式

| 症状 | 可能原因 | 处理 |
|------|---------|------|
| `1.official_init.py` nonce 1582 | 路由器侧 nonce 状态污染 | 重试 2-3 次 |
| `3.enable_ssh.py` TCP 22 永不就绪 | dropbear release 检查未解除 | 检查 sed 是否注入成功 |
| `3.enable_ssh.py` `-100 connect failed` | smartcontroller 进程被 cmdbuf 溢出踩死 | 重启路由器，检查 MAX_CMD_LEN |
| ubiformat 失败 | `/tmp/` 空间不足或固件损坏 | `df -h` 检查，重新 scp |
| reboot 后 192.168.1.1 不通 | uboot flag 没设对 | 上 UART 看 uboot 启动日志 |
| reboot 后仍看到 stock | 启动分区没切成 mtd13 | 重新 `check_boot_partition.sh` 确认当前分区 |

## 参考文件

- 步骤脚本：`src/project/ax6/`（3 个 Python + 2 个 Shell 步骤）
- 工具脚本：`src/project/ax6/miwifi_ssh.sh`、`set_uboot_env.sh`、`check_boot_partition.sh`、`set_miwifi_uboot_partition.sh`
- 文档：`src/project/ax6/doc/flash-pipeline.md`（完整流水线）、`doc/enable-ssh-smartcontroller.md`（漏洞细节）
- 固件：`src/project/ax6/files/*.ubi`
- 本项目内存：`project_ax6_*` 系列（验证记录）
