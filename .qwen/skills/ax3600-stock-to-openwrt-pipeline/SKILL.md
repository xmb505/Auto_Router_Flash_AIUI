---
name: ax3600-stock-to-openwrt-pipeline
description: 小米 AX3600 (R3600) 从 stock 固件刷到 LibWrt 的完整流水线——set_config_iotdev ssid 注入开 SSH（仅 1.0.x 可用，1.1.x 需先降级），SSH ubiformat 刷 .ubi 到非活跃 mtd 并切启动分区；全程不碰 uboot，不开文件服务器；双向圆环已验证（stock↔LibWrt 互切）；含 bdata 持久化 SSH + cron 自愈（xmir 方案）
source: auto-skill
extracted_at: '2026-06-09T19:39:52.346Z'
updated_at: '2026-06-10T03:58:05.056Z'
---

# AX3600 (R3600) stock → LibWrt 批量刷机流水线

## 适用场景

有一台 **小米 AX3600 (R3600)** 路由器（SoC IPQ8071A），需要从 stock 刷到 LibWrt（甲方要求）。工具脚本在 `src/project/ax3600/` 下。**全程不碰 uboot，不开文件服务器**。

**前置**：
- 路由器已在局域网（默认 `192.168.31.1`）
- 你的机器在该网段
- `sshpass` 已安装
- `pycryptodome` 已安装（步骤 1 需要）

## ⚠️ 重要：与 AX6 的关键差异

| 维度 | AX6 (RA69) | AX3600 (R3600) |
|------|-----------|---------------|
| SSH 注入路径 | smartcontroller + 时间操控 (CVE-2023-26319) | **`set_config_iotdev` ssid `;cmd;` 注入** |
| 注入复杂度 | 12 步（含 32s 链路验证）| 4 步（一次性下发）|
| SSH 就绪时间 | ~30-60 秒 | ~20 秒 |
| 固件 1.1.x | 注入**仍可用** | **已被封堵**（`code:1523`）|
| 需要的额外 WiFi/服务 | smartcontroller scene 引擎 | **无**，纯 HTTP API |

**关键警告**：
- `ax6-smartcontroller-exploit` skill **不可用于 AX3600** —— AX3600 上 `xqsmarthome/request_smartcontroller` 返 `Internal Server Error`（无 smartcontroller 服务）
- AX3600 的 `set_config_iotdev` 注入在 **1.1.x 已被封堵**（实测 1.1.25 连合法 SSID 都拒绝）

## 流水线总览（按固件版本分流）

```
[探针] get_router_info.sh  ── 检查 inited / romversion / id
    │                          id 前缀 26677/ = AX3600
    │                          id 前缀 29164/ = AX6
    │
    ├── romversion 1.0.x ──────────────────→ 路径 A（直走）
    │
    └── romversion 1.1.x ──────────────────→ 路径 B（先降级）或 路径 C（跳过 SSH）
```

### 路径 A：1.0.x 工厂态（最简路径）

```
1.official_init.py        ← 工厂态初始化
   ↓
2.login_get_stok.py       ← 拿 stok
   ↓
3.enable_ssh.py --wait    ← set_config_iotdev 注入开 SSH ✅
   ↓
4.official_upgrade.py     ← 可选: 刷 libwrt .ubi 升 OpenWrt
```

### 路径 B：1.1.x 工厂态（降级迂回）

⚠️ **1.1.x 上的 `set_config_iotdev` 已封堵**。要开 SSH 必须先降级。

```
4.official_upgrade.py --file files/R3600_1.0.17.bin
   │  ⚠️ recovery=1 清 NVRAM → 路由器回到 inited=0
   │  ⚠️ 等待 ~45s 重启
   ↓
1.official_init.py        ← 1.0.17 工厂态重新初始化
   ↓
2.login_get_stok.py       ← 拿新 stok
   ↓
3.enable_ssh.py --wait    ← 注入开 SSH ✅
```

### 路径 D（推荐）：开 SSH + ubiformat 到非活跃 mtd

适用于已经通过路径 A/B 获得 SSH 访问的 1.0.17 系统。**这是刷 OpenWrt/LibWrt 的唯一可靠路径**（`4.official_upgrade.py` 不能通过 `upload_rom` 签名校验 `.ubi` 文件，返 `code:1554`）。

```
◉ SSH 已就绪 (root@192.168.31.1)
   │
   ├── scp 上传 libwrt.ubi → /tmp/
   │
   ├── ubiformat /dev/mtdINACTIVE -q -y -f /tmp/libwrt.ubi
   │   └── 探测当前活跃 mtd: cat /proc/cmdline
   │       ubi.mtd=rootfs → 活跃=mtd12, 非活跃=mtd13
   │       ubi.mtd=rootfs_1 → 活跃=mtd13, 非活跃=mtd12
   │
   ├── 设 3 个互补 flag（用 set_miwifi_uboot_partition.sh）
   │
   └── reboot → LibWrt 在 192.168.1.1 上线 (ED25519, SSH password: admin)
```

## 步骤详解

### 阶段 0：探针

```bash
cd src/project/ax3600
bash get_router_info.sh
```

**决策表**：

| `romversion` | `inited` | 决策 |
|--------------|----------|------|
| `1.0.x` | `0` | 路径 A 第 1 步 |
| `1.0.x` | `1` | 路径 A 第 2 步（已知密码）|
| `1.1.x` | `0` | 路径 B 或 C |
| `1.1.x` | `1` | 路径 B 第 1 步先降级 |

**`id` 字段** 前缀确认型号：
- `26677/...` = AX3600
- `29164/...` = AX6（如果是这个，请改用 `ax6-stock-to-openwrt-pipeline` skill）

### 阶段 1：工厂初始化

```bash
python3 1.official_init.py --admin-pwd <密码>
```

**算法**（运行时探测 KEY/IV，不写死任何常量）：
1. 扒 `init.html` → `init.<hash>.js` 提取 KEY/IV
2. 用出厂密码 `admin` + `init=1` 登录拿 stok
3. `set_wan_new` 设 WAN = DHCP
4. `vas_switch` 禁用自动更新
5. `set_router_normal` 设 Wi-Fi + 管理密码（AES-CBC 加密）

**关键注意**：
- `--admin-pwd` **必传**（无默认）
- `--wifi-pwd` 默认等于 `--admin-pwd`
- `--ssid` 默认从 `init_info.routername` 抓
- 固件 ≥ 1.1.x 自动加 `bw160=false` 字段（1.0.x 跳过）
- **nonce 1582 重试**：post-recovery 首次跑可能失败，重试 2-3 次

**输出**：`data.stok` 喂给下一阶段。

### 阶段 2：登录拿 stok（已初始化路由器）

```bash
python3 2.login_get_stok.py --pwd <密码>
```

- 运行时探测 KEY + newEncryptMode（SHA1/SHA256 分支）
- 拒绝工厂态（inited=0 时报错）
- 与 AX6 步骤 2 完全等价

### 阶段 3：set_config_iotdev 注入开 SSH

**这是 AX3600 与 AX6 唯一需要差异化的地方**。

```bash
python3 3.enable_ssh.py --wait
# 或带 --stok 显式
python3 3.enable_ssh.py --stok <token> --wait
# 或自带密码（脚本自己登录）
python3 3.enable_ssh.py --pwd 12345678 --wait
```

**漏洞原理**：
- 端点：`POST /api/misystem/set_config_iotdev?bssid=...&user_id=...&ssid=...`
- `ssid` 字段被 `hostapd` 当 shell 命令行参数解析
- 注入形式：`-h;cmd;`
- 单层 `;` 注入即可，不需要时间操控或 scene 调度

**4 步注入序列**（一次性下发，不需要等链路验证）：

| # | 命令 | 目的 |
|---|------|------|
| 1 | `nvram set flag_last_success=0; ...; nvram set ssh_en=1; nvram commit` | 启用 SSH/telnet/uart/bootflag |
| 2 | `sed -i 's/channel=.*/channel="debug"/g' /etc/init.d/dropbear` | **解除 dropbear release 锁** |
| 3 | `echo -e "root\nroot" > /tmp/psw.txt; passwd root < /tmp/psw.txt; rm -f /tmp/psw.txt` | 设 root 密码 = root |
| 4 | `/etc/init.d/dropbear restart` | 重启 dropbear（**无需重启路由器**）|

**关键差异（vs AX6）**：
- AX3600 的 dropbear release 检查用 `channel=` 关键字（不是 AX6 的 `release=`）
- 完整 dropbear 检查逻辑：
  ```bash
  if [ "$flg_ssh" != "1" -o "$channel" = "release" ]; then
      # 不启动 dropbear
  fi
  ```
  把 `channel` 改成 `debug` 后这个判断放行。

**典型耗时**：~20 秒（等 dropbear 启动 + TCP 22 探测）。

### 阶段 3b（强化）：bdata 持久化 SSH + cron 自愈（xmir 方案）

xmir 项目（`old_coding/router-flash/xmir-patcher/install_ssh.py`）提供了**跨固件版本的通用 SSH 方案**，核心是利用 `bdata` 分区（mtd9）存储硬件级别的 SSH 开关，配合 cron 自愈脚本实现 SSH 永不死。

**原理**：
- `bdata` 是独立的 MTD 分区（mtd9），**不受 firmware 擦写影响**
- `bdata` 存储 `ssh_en`, `telnet_en`, `uart_en`, `boot_wait` 等硬件标志
- 1.0.x 上 `bdata` **原生可写**（无需加载内核模块 xmir_patcher.ko）
- cron 每分钟检查 SSH 状态，挂了自动拉起
- 跨固件升级后，bdata 值仍在

```bash
# 通过 SSH 执行（或用 set_config_iotdev 注入）：
bdata set ssh_en=1
bdata set telnet_en=1
bdata set uart_en=1
bdata set boot_wait=on
bdata commit

# 设自定义 root 密码（xmir 也能做）
echo -e "myCustomPass\nmyCustomPass" | passwd root

# cron 自愈（每分钟检查 + 修复）
crontab -l 2>/dev/null | grep -v ssh_heal > /tmp/cron_new 2>/dev/null || true
echo '* * * * * nvram get ssh_en | grep -q 1 || { nvram set ssh_en=1; nvram commit; /etc/init.d/dropbear restart; }' >> /tmp/cron_new
echo '* * * * * bdata get ssh_en | grep -q 1 || bdata set ssh_en=1; bdata commit' >> /tmp/cron_new
crontab /tmp/cron_new

# 关键 sed + dropbear
sed -i 's/channel=.*/channel="debug"/g' /etc/init.d/dropbear
/etc/init.d/dropbear restart
```

**验证**（2026-06-09, AX3600 1.0.17）：
- `bdata set` 成功，`bdata get ssh_en` → 1 ✅
- `passwd root` 自定义密码 → SSH 登录成功 ✅
- cron 自愈安装 → `crontab -l` 可见 ✅
- 跨 reboot 后 SSH 仍在线 ✅

**bdata vs nvram 区别**：

| | nvram (mtd6 env) | bdata (mtd9) |
|---|-------------------|---------------|
| 作用域 | uboot env + 运行时配置 | 硬件配置 |
| 生存期 | firmware 刷写可擦（recovery=1 清） | 跨 firmware 升级持久 |
| 可写性 | 1.0.x + 1.1.x 均可写 | 1.0.x 可写（无需 kmod）；1.1.x 需加载 xmir_patcher.ko |
| 写保护 | 无 | 1.1.x 有硬件写保护，需内核模块绕过 |

**注意**：bdata 持久化的真正价值在于跨固件升级 —— 如果设了 bdata ssh_en=1 后再 step 4 升级到 1.1.x，新固件可能不会自动开启 SSH（dropbear init 读 nvram，不是 bdata），但 cron 自愈脚本会检测并修复。实际还需要在升级后确保 cron 可持续运行。

### 阶段 4：刷固件（可选）

```bash
# 升/降级 stock 固件
python3 4.official_upgrade.py --stok <token> --file files/R3600_1.0.17.bin

# 直接刷 libwrt (LibWrt) — custom=1 允许非官方
python3 4.official_upgrade.py --stok <token> --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
```

**4 步 API 链**（与 AX6 一字不差）：
1. `upload_rom` — POST multipart/form-data 上传 `.bin`
2. `syslock?flashtype=upload&downgrade=1` — 永远带，免版本检查
3. `flash_permission` — 刷机许可
4. `flash_rom?custom=1&recovery=1` — custom 允许非官方，recovery 清 NVRAM

**⚠️ `recovery=1` 必带**：会清 NVRAM，刷完变 `inited=0`，需重新跑步骤 1。

## ⚠️ 重要：`4.official_upgrade.py` 不能直接刷 OpenWrt

`upload_rom` 阶段有小**小米签名校验**。`.ubi` 格式的 LibWrt/libwrt 在此阶段会返 `code:1554 文件校验失败`。

`custom=1` 只在最终的 `flash_rom` 阶段生效，但文件到不了那一步。

**刷 OpenWrt 的唯一可靠路径**：SSH + ubiformat。

## SSH ubiformat 刷 OpenWrt（路径 D，已验证）

### 步骤

```bash
# 1. 上传 LibWrt .ubi 到路由器 /tmp
sshpass -p root scp -O -oHostKeyAlgorithms=+ssh-rsa \
  files/immortalwrt-25.12.0-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi \
  root@192.168.31.1:/tmp/immortalwrt.ubi

# 2. 探测当前活跃 mtd
ssh root@192.168.31.1 cat /proc/cmdline
# 输出: ubi.mtd=rootfs → 活跃=mtd12, 非活跃=mtd13
# 输出: ubi.mtd=rootfs_1 → 活跃=mtd13, 非活跃=mtd12

# 3. ubiformat 到非活跃 mtd
ssh root@192.168.31.1 ubiformat /dev/mtd13 -q -y -f /tmp/immortalwrt.ubi
# 或 ubiformat /dev/mtd12 -q -y -f ...

# 4. 设启动 flag + reboot
ssh root@192.168.31.1 '
nvram set flag_try_sys1_failed=1
nvram set flag_try_sys2_failed=0
nvram set flag_boot_rootfs=1
nvram commit
reboot'
```

### AX3600 启动分区切换规则（实测修正）

**关键修正**：AX3600 的 boot flag 极性与 AX6 **完全一致**。早期实验中观察 `flag_boot_rootfs` 被 kernel 复位为 0 误判极性相反，后经多次切换实测 cmdline 确认。

AX3600 的 3 个 flag 互补逻辑与 AX6 一字不差：

| 目标 mtd | `flag_try_sys1_failed` | `flag_try_sys2_failed` | `flag_boot_rootfs` |
|----------|------------------------|------------------------|---------------------|
| mtd12 (rootfs / stock) | 0 | 1 | 0 |
| mtd13 (rootfs_1 / LibWrt) | 1 | 0 | 1 |

**三 flag 必须一起设**。只改 `flag_boot_rootfs` 不保证切换——uboot 同时检查 `flag_try_sysN_failed`。

**注意**：
- `flag_try_sysN_failed=1` 表示"该 sys 失败，跳过不启动"
- 切换分区时设的是**对侧**的 sys 为 failed: 切到 mtd13 设 `sys1_failed=1`, 切到 mtd12 设 `sys2_failed=1`
- `bootargs` 在 mtd6 中的值可以被写入，但 kernel 启动时会根据实际 boot 行为**重写**——改 `bootargs` 不能控制 boot 分区

### 验证

```bash
# LibWrt 上线后验证
sshpass -p admin ssh -o StrictHostKeyChecking=no root@192.168.1.1 '
cat /etc/openwrt_release
ubus call system board
'
# 期望输出:
#   DISTRIB_ID=LibWrt
#   model=Xiaomi AX3600 (stock layout)
#   board_name=xiaomi,ax3600-stock
#   SSH password: admin
```

## 决策矩阵：选择哪条路径

```
START
  │
  ├─ 想要 SSH 访问? ─┐
  │                  │
  │                YES
  │                  │
  │  路由器是什么固件?
  │   │
  │   ├─ 1.0.x ─→ 路径 A (init → login → enable_ssh)
  │   │
  │   └─ 1.1.x ─→ 路径 B (downgrade → init → login → enable_ssh)
  │                  ↑
  │                  └─ recovery=1 清 NVRAM, 降级后回到 inited=0
  │
  └─ 直接刷 OpenWrt, 不要 SSH? ─→ 路径 C (login → upgrade)
                                      ↑
                                      └─ custom=1 允许非官方固件
```

## 双系统回退（双向圆环实测验证）

刷完后 mtd12 是 stock 1.0.17, mtd13 是 LibWrt 25.12。两个方向来回切均已实测验证。

### 方向 A：LibWrt → 小米 stock

LibWrt 下用 `fw_setenv` 写 uboot env flag（没有 `nvram`）：

```bash
# 一键脚本（推荐）
./switch_to_stock.sh
# 输出: {"ok":true,"next_ip":"192.168.31.1"}
# 等 ~45s → stock 回到 192.168.31.1

# 等价手动操作
ssh root@192.168.1.1 \
  "fw_setenv flag_try_sys1_failed 0 && \
   fw_setenv flag_try_sys2_failed 1 && \
   fw_setenv flag_boot_rootfs 0 && \
   reboot"
```

**验证 (2026-06-09)**：LibWrt 25.12.0 → `switch_to_stock.sh` → stock 1.0.17 ✅ `inited=1` 保留

### 方向 B：小米 stock → LibWrt

```bash
./set_miwifi_uboot_partition.sh --part 1 --ip 192.168.31.1
./miwifi_ssh.sh --cmd reboot
# 路由器从 mtd13 启动（LibWrt），回到 192.168.1.1, ED25519, SSH password: admin
```

**验证 (2026-06-09)**：stock 1.0.17 → `set_miwifi_uboot_partition.sh --part 1` → LibWrt 25.12 ✅

### 方向 C：任何状态 → 自动选对侧（推荐初始烧写）

使用 `6.miwifi_2_openwrt.py` 时不传 `--part`，脚本自动探测当前活跃 mtd 和对侧：

```bash
# 自动选对侧：无论活跃是 mtd12 还是 mtd13
python3 6.miwifi_2_openwrt.py --file-name immortalwrt.ubi
```

## 双系统互切（图形示意）

```
         mtd12 (rootfs)        mtd13 (rootfs_1)
       ┌────────────────┐  ┌────────────────────┐
       │ 小米 stock 1.0.17 │  │ LibWrt 25.12.0 │
       │ 192.168.31.1      │  │ 192.168.1.1         │
       └───────┬──────────┘  └────────┬────────────┘
               │                       │
               │ ┌─────────────────┐  │
               │ │set_miwifi_uboot │  │
               │ │_partition.sh    │  │
               └─│     --part 1    ├──┘
               ┌─│     --part 0    ├──┐
               │ └─────────────────┘  │
               │                       │
               └───────┬──────────────┘
                       │
           物理 reset / recovery

| 日期 | 机身 | 路径 | 结果 |
|------|------|------|------|
| 2026-06-09 | `26677/E0P534252` | 路径 B: 1.1.25 → 4 降级 → 1 init → 2 login → 3 enable_ssh | ✅ 4 步注入全过，~20s SSH 就绪 |
| 同上 | 同上 | SSH 验证：`nvram get ssh_en=1`, `channel="debug"` | ✅ 验证通过 |
| 2026-06-09 | `26677/E0P534252` | 路径 D: SSH ubiformat → 3‑flag 切 mtd13 → reboot → LibWrt | ✅ Kernel 6.12.87, LibWrt 25.12.0 |
| 同上 | 同上 | LibWrt 验证：`ssh root@192.168.1.1`, no password, ED25519 | ✅ LuCI + SSH 全功能 |
| 同上 | 同上 | **圆环 A**: LibWrt → `switch_to_stock.sh` → stock 1.0.17 | ✅ `inited=1` 保留, SSH 关闭 |
| 同上 | 同上 | **圆环 B**: stock 1.0.17 → `set_miwifi_uboot_partition.sh --part 1` → LibWrt | ✅ ED25519 免密, 192.168.1.1 |

## 失败模式速查

| 症状 | 可能原因 | 处理 |
|------|---------|------|
| 步骤 3 返 `code:1523 参数错误` | **1.1.x 已封堵 iotdev** | 走路径 B（先降级）或路径 C（跳过 SSH）|
| 步骤 3 ssh_wait 超时 | sed channel 注入未生效 / dropbear 没起来 | SSH 进路由器看 `cat /etc/init.d/dropbear \| grep channel` |
| 步骤 1 nonce 1582 | 首次 init 偶发 | 重试 2-3 次 |
| 步骤 1 报 `code 401 not auth` | 路由器已初始化 | 跳过步骤 1，先 `router_official_recovery.sh` |
| 步骤 4 报 `code 1532` | 固件签名不对（用了 AX6 的 RA69 .bin）| 用对型号的 `R3600_*.bin` |
| SSH 进去看不到 nvram | 用了不带 `nvram` 的非 stock 固件 | 确认是从 stock 1.0.17/1.1.25 启动的 |

## 与 AX6 skill 的关系

- **本 skill**：AX3600 专用，用 `set_config_iotdev` 注入
- **`ax6-stock-to-openwrt-pipeline` skill**：AX6 专用，用 smartcontroller 注入
- **不可互换**：检测 `id` 字段前缀判断型号
  - `26677/` → AX3600 → 本 skill
  - `29164/` → AX6 → 旧 skill

## 参考文件

- 步骤脚本：`src/project/ax3600/1.official_init.py`、`2.login_get_stok.py`、`3.enable_ssh.py`、`4.official_upgrade.py`、`5.firmware_upload_on_miwifi.sh`、`6.miwifi_2_openwrt.py`、`7.custom_openwrt.py`
- 工具脚本：`src/project/ax3600/miwifi_ssh.sh`、`get_router_info.sh`、`router_official_recovery.sh`、`switch_to_stock.sh`、`set_miwifi_uboot_partition.sh`、`check_boot_partition.sh`、`set_uboot_env.sh`
- 文档：`src/project/ax3600/doc/README.md`、`doc/flash-pipeline.md`、`doc/enable-ssh-iotdev.md`、`doc/玩法说明书.md`、`doc/switch-to-stock.md`、`doc/custom-openwrt.md`
- 固件：`src/project/ax3600/files/R3600_1.0.17.bin`、`files/immortalwrt-25.12.0-...factory.ubi`、`files/libwrt-...factory.ubi`
- 项目内存：`project_ax3600_set_config_iotdev_patched.md`、`project_ax3600_boot_flag_polarity.md`
