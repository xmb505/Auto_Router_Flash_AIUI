# AX3000T 刷机流水线 (Flash Pipeline)

## 概述

小米路由器 AX3000T (RD03) 从 stock 固件到 OpenWrt 的端到端刷机流程。

⚠️ **AX3000T 的刷机流程与 AX5/AX6 根本性不同**：
AX5/AX6 用 `ubiformat` 直刷 rootfs mtd；
AX3000T 先刷自定义 uboot (FIP)，uboot 自动从 TFTP 拉取 initramfs recovery，最后 sysupgrade。

## 总览（最简路径 — start_binding 可用）

```
步骤 1: 1.official_init.py           ← 出厂初始化（设密码）
步骤 2: 2.login_get_stok.py          ← 用新密码登录拿 stok
步骤 4: 4.enable_ssh.py              ← start_binding 注入开 SSH (root/root)
步骤 5: 5.flash_uboot.py             ← SCP + mtd write 刷自定义 uboot (FIP)
步骤 6: 6.tftp_recovery.py           ← 架设 TFTP，uboot 自动拉取 initramfs-recovery.itb
步骤 7: 7.sysupgrade_openwrt.py      ← initramfs 内 sysupgrade 到完整 OpenWrt
```

## 总览（降级迂回路径 — start_binding 被修补）

```
步骤 1: 1.official_init.py           ← 初始化
步骤 2: 2.login_get_stok.py          ← 拿 stok
步骤 3: 3.downgrade.py               ← 降级到 1.0.47 (清 NVRAM, inited→0)
         ↓ ~45s 重启
步骤 1: 1.official_init.py           ← 重新初始化
步骤 2: 2.login_get_stok.py          ← 重新拿 stok
步骤 4: 4.enable_ssh.py              ← 注入开 SSH
步骤 5-7: 同上
```

## 步骤详解

### 步骤 1：出厂初始化（`1.official_init.py`）

工厂态路由器首次 WEB 初始化。运行时扒 KEY/IV。

```bash
python3 1.official_init.py --admin-pwd 12345678
```

**AX3000T 特有**：
- 出厂登录: GET 明文 `password=admin&init=1`（无需 nonce）
- WAN 设置: POST `autoset=1`
- 密码哈希: SHA256 oldPwd + newPwd (SHA1-AES) + **newPwd256** (SHA256-AES)
- 额外字段: `update=1`, `bw160=1`, `bsd=1`

⚠️ 返回的 stok 改密后立即失效，**必须**用步骤 2 重新登录。

### 步骤 2：登录获取 stok（`2.login_get_stok.py`）

```bash
python3 2.login_get_stok.py --pwd 12345678
```

**AX3000T 特有**：POST + SHA256（AX5 用 GET + SHA1）

### 步骤 3：降级（可选，`3.downgrade.py`）

仅在 `start_binding` 注入被新固件修补时使用。

```bash
python3 2.login_get_stok.py --pwd 12345678 | \
  python3 3.downgrade.py --file files/RD03_1.0.47.bin
```

`recovery=1` 清 NVRAM，重启后 `inited=0`，需重跑步骤 1+2。

### 步骤 4：启用 SSH（`4.enable_ssh.py`）

通过 `start_binding` API 的 key 参数注入命令开 SSH。

```bash
python3 2.login_get_stok.py --pwd 12345678 | python3 4.enable_ssh.py
```

详见 [`enable-ssh.md`](enable-ssh.md)。

**AX3000T 特有**：
- API: `/api/xqsystem/start_binding`（AX5 用 `set_config_iotdev`）
- 注入字段: `key`（AX5 用 `ssid`）
- 一次发送所有命令，无需分块

SSH 连接: `sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1`

### 步骤 5：刷自定义 uboot (FIP)（`5.flash_uboot.py`）

```bash
python3 5.flash_uboot.py
# 或指定文件:
python3 5.flash_uboot.py --file files/immortalwrt-25.12.0-...-bl31-uboot.fip
```

**AX3000T 独有步骤**（AX5/AX6 不需要）：
1. SCP 上传 `.fip` → `/tmp/uboot.fip`
2. SSH 验证 MD5
3. SSH `mtd write /tmp/uboot.fip FIP && sync`
4. SSH `reboot` → 自定义 uboot 接管

### 步骤 6：TFTP recovery 引导 initramfs（`6.tftp_recovery.py`）

```bash
python3 6.tftp_recovery.py --debug
```

**AX3000T 独有步骤**。自定义 uboot 内置 TFTP recovery：
1. 主机架设 TFTP 服务器（dnsmasq/atftpd）
2. 放入 initramfs-recovery.itb
3. 配置主机网卡为 192.168.1.x/24
4. reboot 路由器，uboot 自动从 TFTP 拉取 recovery 并启动
5. 等待 initramfs SSH 上线 (192.168.1.1)

前置条件：主机需安装 `dnsmasq` 或 `atftpd`。

### 步骤 7：sysupgrade 到完整 OpenWrt（`7.sysupgrade_openwrt.py`）

```bash
python3 7.sysupgrade_openwrt.py
```

从 initramfs 系统内执行 `sysupgrade -n`，刷入持久 OpenWrt。

## 一键命令（最简路径）

```bash
cd src/project/ax3000t

# 步骤 1: 初始化（丢弃返回的 stok）
python3 1.official_init.py --admin-pwd 12345678

# 步骤 2: 用新密码重新登录
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 步骤 4: 开 SSH
python3 4.enable_ssh.py --stok "$STOK"

# 验证 SSH
./miwifi_ssh.sh --cmd 'cat /proc/version'

# 步骤 5: 刷 uboot (FIP)
python3 5.flash_uboot.py

# 步骤 6: TFTP recovery 引导 initramfs
python3 6.tftp_recovery.py --debug

# 步骤 7: sysupgrade
python3 7.sysupgrade_openwrt.py
```

## 实测时间表

| 阶段 | 预估耗时 |
|------|---------|
| 1.official_init | ~3s |
| 2.login_get_stok | <1s |
| 4.enable_ssh | ~30s（含 SSH 端口等待）|
| 5.flash_uboot | ~10s（上传 + mtd write）|
| 6.tftp_recovery | ~1-2min（TFTP 传输 + initramfs 启动）|
| 7.sysupgrade_openwrt | ~2-3min（刷写 + 重启）|

## 失败模式速查

| 现象 | 阶段 | 原因 | 解决 |
|------|------|------|------|
| `start_binding` 返回错误 | 4 | 新固件已修补漏洞 | 先步骤 3 降级到 1.0.47 |
| 登录 `code 401` | 1/2 | 路由器已初始化 | 跳过步骤 1；用正确密码 |
| `flash_rom` 报 `code:1532` | 3 | 固件签名不对 | 用 RD03 专用 `.bin` |
| MD5 不匹配 | 5 | SCP 传输损坏 | 重传 |
| TFTP 服务器未安装 | 6 | 主机缺 dnsmasq/atftpd | `sudo apt install dnsmasq` |
| sysupgrade 失败 | 7 | 文件类型不对 | 用 `.itb` 不是 `.bin` |

## 验证清单

刷完后 SSH 进 OpenWrt 确认：

```bash
# OpenWrt 版本
cat /etc/openwrt_release

# 分区信息
cat /proc/mtd

# 网络
ip addr show
```

## 关联文档

- [enable-ssh.md](enable-ssh.md) — start_binding 注入机制详解
- [model-info.md](model-info.md) — 硬件参数 + MTD 表
- [troubleshooting.md](troubleshooting.md) — 错误 reason 索引
