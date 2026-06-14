---
name: ax3000t-stock-to-openwrt-pipeline
description: 小米 AX3000T (RD03) 从 stock 固件刷到 ImmortalWrt/OpenWrt 的完整流水线——start_binding 注入启用 SSH + FIP uboot 替换 + sysupgrade initramfs + custom overlay，全步骤定义（含 old_coding 参考和 hackCheck 绕过细节）
source: auto-skill
extracted_at: '2026-06-14T08:08:17.105Z'
---

# AX3000T (RD03) stock → OpenWrt 刷机流水线

## 机型特征

| 项目 | 值 |
|------|-----|
| 型号 | 小米 AX3000T (RD03) |
| SoC | MediaTek MT7981 (Filogic 820) |
| 架构 | ARMv8 Cortex-A53 (aarch64) |
| 内核 (stock) | 5.4.171 |
| 分区关键 | mtd5 = **FIP** (uboot FIT image, 2MB) |
| 与 IPQ 差异 | **无** ubiformat / dual-system；走 **FIP 替换 + uboot TFTP recovery**（原计划）或 **直接 sysupgrade**（当前方案） |
| 出厂登录 | newEncryptMode=1 (SHA256)，POST 方式 |
| KEY/IV | 运行时从 `init.html` → `init.<hash>.js` 扒取，回退已知常量 `a2ffa5c9be07488bbb04a3a47d3c5f6a` / `64175472480004614961023454661220` |

## SSH 漏洞路径：start_binding key 注入

AX3000T 不走 AX6 的 `smartcontroller scene`（CVE-2023-26319），也不走 AX3600 的 `set_config_iotdev ssid` 注入。它走 **`/api/xqsystem/start_binding` 的 `key` 参数注入**。

### hackCheck 绕过

`start_binding` 内部有 hackCheck v2 过滤 `;` 和 `|`，但 `\n`（换行符）未被过滤。用 `\n` 替代 `;` 即可串联多条命令。

### payload 格式

```
1234' -X \n<cmd1>\n<cmd2>\n...\n logger -t X 'X
```

### 注入命令序列（一次发送全部）

| 顺序 | 命令 | 作用 |
|------|------|------|
| 1 | `sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear` | 解除 dropbear release 检查（小米魔改限制） |
| 2 | `nvram set ssh_en=1` | 持久化 SSH 开关 |
| 3 | `nvram set boot_wait=on` | 启用 boot_wait |
| 4 | `nvram commit` | 写入 NVRAM |
| 5 | `echo -e 'root\nroot' > /tmp/psw.txt` | 准备密码文件 |
| 6 | `passwd root < /tmp/psw.txt` | 设 root 密码 |
| 7 | `/etc/init.d/dropbear enable` | 启用 dropbear |
| 8 | `/etc/init.d/dropbear restart` | 启动 dropbear |

### 安全注入

注入时替换命令中的 `;` 和 `|` 为 `\n` 防止 hackCheck 拦截：

```python
cmd = cmd.replace(";", "\n").replace("|", "\n")
```

### SSH 验证

- 注入后 SSH 秒级就绪（无需重启）
- 用户 `root`，密码 `root`
- 算法 `ssh-rsa`（dropbear 旧版），连接加 `-oHostKeyAlgorithms=+ssh-rsa`
- 等待方式：TCP socket 探测端口 22，最长 60s，2s 间隔轮询

## 完整流水线（6 步）

| 步骤 | 脚本 | 功能 | 默认 SSH |
|------|------|------|----------|
| 1 | `1.official_init.py` | 出厂初始化（设 Wi-Fi + 管理密码） | — |
| 2 | `2.login_get_stok.py` | POST + SHA256 登录，获取 stok | — |
| 3 | `3.enable_ssh.py` | **start_binding 注入**启用 SSH | root/root |
| 4 | `4.flash_uboot.py` | SSH + `mtd write` FIP 分区换 uboot | root/root |
| 5 | `5.sysupgrade_openwrt.py` | SSH `sysupgrade -n` 烧完整 sysupgrade.itb | root/空密码 |
| 6 | `6.custom_openwrt.py` | SCP + tar overlay → reboot | root/空密码 |

### 步骤 1：出厂初始化
- AX3000T 使用 `newEncryptMode=1`（SHA256），不同于老机型的 SHA1
- `init_info` 取固件版本和默认 SSID
- 登录用 `GET` 明文密码 + `init=1`（出厂态）
- 设置 Wi-Fi 同时传 `oldPwd`（SHA256）、`newPwd`（SHA1-AES 兼容）、`newPwd256`（SHA256-AES 新模式）——AX3000T 新增 `bw160=1`、`bsd=1`、`update=1` 字段

### 步骤 2：登录
- 非出厂态登录用 **POST** `/api/xqsystem/login`
- 密码哈希格式：`SHA256(nonce + SHA256(pwd + KEY))`，不同于 AX5/AX3600 的 SHA1

### 步骤 3：SSH 启用（核心差异点）
- API：`/api/xqsystem/start_binding`（参数 `uid=1234&key=<payload>`）
- 不走 `set_config_iotdev` 或 `smartcontroller`
- payload 中 `\n` 绕过 hackCheck 对 `;`/`|` 的过滤
- 注入后**无需重启**，dropbear 立即启动

### 步骤 4：刷 uboot (FIP)
- SCP 上传 `.fip` 文件到 `/tmp/uboot.fip`
- SSH 验证 MD5 后 `mtd write /tmp/uboot.fip FIP`
- 用 label `FIP` 而非 mtd 编号（mtd5）
- 完成后 `reboot`

### 步骤 5：sysupgrade OpenWrt
- initramfs 系统（IP 变更为 `192.168.1.1`）已启动
- SCP 上传 `.itb` 文件到 `/tmp/`
- SSH `sysupgrade -n`（不保留配置）
- 等待路由器重启上线

### 步骤 6：custom overlay
- OpenWrt 已上线后，SCP 上传 `overlay-new.tar.gz`
- SSH 解压到 `/overlay/upper/` → `reboot`

## 与 IPQ 系列的关键差异

| 维度 | AX3000T (MT7981) | AX6/AX3600 (IPQ8071A) |
|------|-------------------|----------------------|
| 漏洞路径 | start_binding key 注入 | set_config_iotdev / smartcontroller |
| 绕过方式 | `\n`（换行符） | `;`（分号不受限） |
| boot 分区 | mtd5 FIP（单分区） | mtd12 rootfs / mtd13 rootfs_1（双系统） |
| 刷机方式 | mtd write FIP | ubiformat 非活跃 rootfs |
| 降级需求 | 否（start_binding 在 stock 固件普遍可用） | 有时需要（set_config_iotdev 被后续固件修补） |
| 加密模式 | SHA256 (newEncryptMode=1) | SHA1 (newEncryptMode=0) 或 SHA256 |
| 重启需求 | 无需重启（SSH 秒级就绪） | AX5 需重启，AX3600 秒级 |

## 编排器（一键刷机）

`ax3000t/all_official_2_openwrt.py` 封装了 6 步全流程。用 INI 配置文件驱动：

```ini
[firmware]
uboot_file = files/immortalwrt-...-ubootmod-bl31-uboot.fip
sysupgrade_file = files/immortalwrt-...-ubootmod-squashfs-sysupgrade.itb
overlay_file = files/overlay-mocktool.tar.gz
```

```bash
python3 all_official_2_openwrt.py
```

### 编排器执行逻辑

```
--step 1（默认）: 完整流水线
ping → init_info → 验证 RD03 →
  inited=1 → 报错要求 Reset
  inited=0 → init → login → enable_ssh
  → 4.flash_uboot（mtd write FIP → 自动重启 + TFTP 拉 initramfs）
  → sleep(60) 等 initramfs 启动
  → 5.sysupgrade_openwrt（scp → sysupgrade → 等重启）
  → 6.custom_openwrt（可选 overlay）

--step 5: initramfs 模式（路由器已在 192.168.1.1 initramfs）
  → 跳过 stock 所有阶段
  → 5.sysupgrade_openwrt
  → 6.custom_openwrt（可选）
```

### 注意事项

- **前置条件**：主机需要运行 TFTP 服务器提供 initramfs-recovery.itb
- **IP 切换**：stock 系统在 192.168.31.1，刷 FIP 重启后 initramfs/OpenWrt 在 192.168.1.1
- **sleep(60)**：`4.flash_uboot` 后必须等 60s 让 uboot 完成 TFTP 拉取 initramfs 启动，再跑 sysupgrade
- **sysupgrade 等待**：`5.sysupgrade_openwrt.py` 的 `wait_openwrt_boot()` 先等 SSH 断连（sysupgrade 触发重启），再等上线（新系统就绪），避免 initramfs SSH 残留导致误判

### 实机验证（2026-06-14）

- 型号：AX3000T (RD03)
- 固件：1.0.47（出厂态，需 init）
- SSH：start_binding 注入一次成功（SSH 秒级就绪）
- FIP：`4.flash_uboot.py --file uboot.fip` 成功写入 mtd5
- 重启后：TFTP 正常拉取 initramfs，192.168.1.1 约 7s 上线
- sysupgrade：`5.sysupgrade_openwrt.py --file sysupgrade.itb` 完成
- overlay：`6.custom_openwrt.py --file overlay-mocktool.tar.gz` 完成

## 来源

- `old_coding/Auto_Flash_Router/AX3000T/enable_ssh.py` — 原始注入实现
- `old_coding/Auto_Flash_Router/AX3000T/rce.py` — 通用注入工具（含 `;`/`|` → `\n` 安全替换）
- `old_coding/Auto_Flash_Router/AX3000T/auto_init.py` — 出厂初始化参考
- `src/project/ax3000t/` — 当前重构的步骤脚本（含编排器）
- 2026-06-14 实机验证：全链路 1.0.47 → OpenWrt
