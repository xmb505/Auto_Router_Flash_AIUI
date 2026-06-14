# AX5 硬件参数 (Model Info)

> AI 不硬编码路由器知识——本文档是**事实表**，所有数值以实机探测为准。

## 设备身份

| 项目 | 值 | 来源 |
|------|-----|------|
| 品牌 / 型号 | Redmi AX5 / 小米路由器 RA67 | `model: "xiaomi.router.ra67"` |
| SoC | Qualcomm IPQ6000 (ARMv7) | `uname -m` |
| 架构 | armv7l | stock `uname -a` |
| 硬件代号 | RA67 | `init_info.hardware` |
| 默认管理 IP | `192.168.31.1` | 小米 stock 系 |
| OpenWrt 默认 IP | `192.168.1.1` | LibWrt/OpenWrt |
| 默认 stock 密码 | 无 / 首次 init 时设 | — |
| 默认 OpenWrt 密码 | `admin`（LibWrt 编译时设置）| 实测 SSH |

## 加密参数 (KEY / IV / 模式)

| 项目 | 值 | 备注 |
|------|-----|------|
| KEY（已知常量）| `a2ffa5c9be07488bbb04a3a47d3c5f6a` | 老代码沿用的硬编码值 |
| IV（已知常量）| `64175472480004614961023454661220` | 同上 |
| 加密模式 | SHA1 only (`newEncryptMode=0`) | **无 SHA256** |
| KEY/IV 来源策略 | 优先扒 `init.<hash>.js`，失败回退已知常量 | 实测两个固件（1.0.26/1.4.31）JS 中均能找到同样值 |

> **新固件兼容性**：脚本每次 init/login 时**运行时**扒当前固件的 `init.<hash>.js` 拿 KEY/IV，
> 不在代码或文档里"固化"新值。新固件出现时按"先跑 `1.official_init.py` 看结果"流程处理。

## Flash 布局 (`/proc/mtd` 实测)

```
dev:    size    erasesize  name
mtd0:   00180000 00020000 "0:SBL1"
mtd1:   00100000 00020000 "0:MIBIB"
mtd2:   00380000 00020000 "0:QSEE"
mtd3:   00080000 00020000 "0:DEVCFG"
mtd4:   00080000 00020000 "0:RPM"
mtd5:   00080000 00020000 "0:CDT"
mtd6:   00080000 00020000 "0:APPSBLENV"
mtd7:   00180000 00020000 "0:APPSBL"
mtd8:   00080000 00020000 "0:ART"
mtd9:   00080000 00020000 "bdata"
mtd10:  00080000 00020000 "crash"
mtd11:  00080000 00020000 "crash_syslog"
mtd12:  00080000 00020000 "0:BOOTCONFIG"
mtd13:  00080000 00020000 "0:BOOTCONFIG1"
mtd14:  00380000 00020000 "0:QSEE_1"
mtd15:  00080000 00020000 "0:DEVCFG_1"
mtd16:  00080000 00020000 "0:RPM_1"
mtd17:  00080000 00020000 "0:CDT_1"
mtd18:  02400000 00020000 "rootfs"      ← 双系统分区 A（36MB）
mtd19:  02400000 00020000 "rootfs_1"    ← 双系统分区 B（36MB）
mtd20:  024a0000 00020000 "overlay"
mtd21:  00080000 00020000 "cfg_bak"
mtd22:  003a2000 0001f000 "kernel"
mtd23:  01341000 0001f000 "ubi_rootfs"
mtd24:  00915000 0001f000 "rootfs_data"
mtd25:  02093000 0001f000 "data"
```

## 关键 MTD 映射

| 用途 | 编号 | 备注 |
|------|------|------|
| 根文件系统 A | **mtd18** = `rootfs` (36MB) | 烧 OpenWrt 候选 |
| 根文件系统 B | **mtd19** = `rootfs_1` (36MB) | 烧 OpenWrt 候选 |
| 引导配置 | mtd12 / mtd13 = `BOOTCONFIG` / `BOOTCONFIG1` | **不碰** |
| U-Boot ENV | mtd6 = `APPSBLENV` | **不碰**（脚本不写 mtd6）|
| 加密/校准 | mtd8 = `ART` | **绝对不碰** |
| MIBIB | mtd1 | **不碰**（学 AX6 流程） |

> **设计原则：学 AX6 直接写到非活跃 rootfs，不动 uboot/mtd6/mtd1**。
> 由 `set_miwifi_uboot_partition.sh` 改 `nvram flag_boot_rootfs` 切启动。

## 启动分区判定

权威来源：`/proc/cmdline` 里的 `ubi.mtd=...`：

| cmdline 片段 | 当前活跃 MTD | 下次启动（nvram flag）|
|--------------|--------------|------------------------|
| `ubi.mtd=rootfs` | **mtd18** | `flag_boot_rootfs=0` |
| `ubi.mtd=rootfs_1` | **mtd19** | `flag_boot_rootfs=1` |

切分区 = 改 3 个 nvram flag（互补设置）：

| 切到 | `flag_try_sys1_failed` | `flag_try_sys2_failed` | `flag_boot_rootfs` |
|------|------------------------|------------------------|---------------------|
| **part=0** → mtd18 (rootfs) | `0` | `1` | `0` |
| **part=1** → mtd19 (rootfs_1) | `1` | `0` | `1` |

工具脚本：`./set_miwifi_uboot_partition.sh --part 0|1`

## Stock 与 OpenWrt 关键差异

| 项目 | Stock (小米) | OpenWrt / LibWrt |
|------|--------------|------------------|
| 默认 IP | `192.168.31.1` | `192.168.1.1` |
| SSH 主机密钥 | RSA | ED25519 |
| SSH 连接算法 | 需 `-oHostKeyAlgorithms=+ssh-rsa` | 默认即可 |
| 文件系统 | UBI + squashfs | UBI + squashfs（OpenWrt 镜像自带）|
| 默认 root 密码 | 无 | `admin`（LibWrt）|
| Web 入口 | miwifi luci | OpenWrt luci |
| 内核版本（实测）| 4.4.60 | 6.12.87 (LibWrt 25.12-SNAPSHOT) |
| 架构 | armv7l 32-bit | aarch64 64-bit |

## 固件文件

| 文件 | 大小 | 用途 |
|------|------|------|
| `files/RA67_1.0.26.bin` | 25,653,096 B (25MB) | 降级目标（修复 SSH 漏洞前的旧固件）|
| `files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi` | 25,165,824 B (24MB) | OpenWrt 镜像（factory 模式）|
| `files/mocktool-overlay.tar.gz` | — | 自定义 overlay（可选）|

## 关联文档

- [flash-pipeline.md](flash-pipeline.md) — 端到端刷机流水线
- [enable-ssh.md](enable-ssh.md) — `set_config_iotdev` ssid 注入开 SSH
- [troubleshooting.md](troubleshooting.md) — `reason` 字段 → 恢复方案
