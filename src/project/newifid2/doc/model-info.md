# Newifi D2 (新路由 D2 / Newifi 3) — 机型信息

**注意**：Newifi D2 不是小米/Redmi 路由器，不适用 Xiaomi 密码学/API 体系。本目录的脚本从零构建。

## 硬件规格

| 项目 | 规格 |
|------|------|
| SoC | MediaTek MT7621AT (MIPS 1004Kc v2.15, 双核 880MHz) |
| RAM | 512 MB DDR3 |
| Flash | 32 MB SPI NOR (Winbond W25Q256FV) |
| Wi-Fi | MT7603EN (2.4GHz) + MT7612EN (5GHz) |
| Switch | MT7530 (内置, 千兆) |
| USB | USB 3.0 x1 |
| 架构 | mipsel (mips 小端) |

## Flash 布局 (典型 OpenWrt)

| 分区 | 偏移 | 大小 | 说明 |
|------|------|------|------|
| u-boot | 0x000000 | 0x30000 (192K) | Bootloader |
| u-boot-env | 0x030000 | 0x10000 (64K) | U-Boot 环境变量 |
| factory | 0x040000 | 0x10000 (64K) | Wi-Fi 校准数据 (EEPROM) |
| firmware | 0x050000 | 0x1fb0000 (~31.7M) | OpenWrt 固件 (kernel+rootfs) |
| --- | --- | --- | --- |
| **MTD 映射 (OpenWrt)** | | | |
| mtd0 | | SPI-NOR 全片 | |
| mtd1 | | u-boot | |
| mtd2 | | u-boot-env | |
| mtd3 | | factory | |
| mtd4 | | firmware | |
| mtd5 | | kernel (firmware 内) | |
| mtd6 | | rootfs (firmware 内) | |
| mtd7 | | rootfs_data | |

> 注意：SPI NOR 没有 UBI，没有 dual-image 双系统。firmware 分区包含 kernel + squashfs rootfs。

## 默认网络

| 项目 | 值 |
|------|-----|
| 默认 IP | `192.168.99.1`（stock）/ `192.168.1.1`（breed/OpenWrt） |
| 默认子网 | `255.255.255.0` |
| 默认 SSH | OpenWrt: root (无密码) |
| 默认 Wi-Fi | OpenWrt: 关闭 |

## 刷机方式

| 方法 | 适用固件 | 说明 |
|------|---------|------|
| ** breed Web 恢复** | 任何 | 按住 reset 上电 → `192.168.1.1` → 网页上传 |
| ** mtd write** | OpenWrt sysupgrade | SSH 进系统后 `mtd write <file> firmware` |
| ** sysupgrade** | OpenWrt sysupgrade | `sysupgrade -n <file>` (保留/清空配置) |
| ** TFTP 恢复** | breed 下可用 | breed 内置 TFTP 客户端 |

## Breed Bootloader

Newifi D2 出厂使用**官方 uboot**；常见第三方 bootloader 是 **breed**（hackpascal 开发）：
- 按住 Reset 上电 → LED 闪烁 → 浏览器打开 `192.168.1.1`
- 支持 Web 上传刷机、环境变量编辑、EEPROM 备份
- 进入 breed 后可通过 `breed Enter` 命令进入命令行

### Breed Web API（实测 2026-06-10）

Web 服务在 `http://192.168.1.1/`：

#### 固件更新页面 `/upgrade.html`

导航入口是 `/upgrade.html`，表单提交到 `POST /upload.html`（multipart/form-data）。

**两种模式**：

**⚠️ breed 严禁刷入 sysupgrade 固件！** Sysupgrade 是 OpenWrt 专有格式，breed 不识别。Breed 只接受裸 firmware 镜像（initramfs-kernel 或编程器固件）。

**刷 sysupgrade 的正确路径**：
1. breed 刷 `initramfs-kernel.bin` → 启动到 initramfs 系统
2. initramfs shell 里 `scp` 上传 sysupgrade.bin
3. initramfs shell 里 `sysupgrade -n <file>` → 写持久 rootfs + 自动重启

**generic 模式字段**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `fw_type` | ✅ | hidden, 固定 `generic` |
| `fw_check` | ✅ | checkbox `=1`，勾选才上传 fw_file |
| `fw_file` | ✅ | **initramfs-kernel.bin**（裸 kernel+initrd） |
| `flash_layout` | ✅ | select, D2 选 `reference`（kernel @ 0x50000） |
| `autoreboot` | ❌ | checkbox `=1`，**刷完自动重启，推荐勾选** |
| `submit` | ✅ | hidden, 固定 `Upload` |
| `boot_file` + `boot_check` | ❌ | 同步刷 bootloader |
| `eeprom_file` + `eeprom_check` | ❌ | 同步刷 Wi-Fi 校准 |

**fullflash 模式字段**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `fw_type` | ✅ | hidden, 固定 `fullflash` |
| `fullflash_check` | ✅ | checkbox `=1` |
| `fullflash_file` | ✅ | 完整 32MB flash dump |
| `autoreboot` | ❌ | checkbox `=1`，刷完自动重启 |
| `skipboot` | ❌ | checkbox `=1`，保留现有 Bootloader（默认勾选） |
| `skipeeprom` | ❌ | checkbox `=1`，保留现有 EEPROM（默认勾选） |
| `submit` | ✅ | hidden, `Upload` |

**Flash 布局选项**（`flash_layout`）：

| 值 | 含义 | 适用 |
|----|------|------|
| `reference` | kernel @ 0x50000 | **D2 默认** |
| `compact` | kernel @ 0x40000 | |
| `big` | kernel @ 0x60000 | |
| `phicomm` | kernel @ 0xA0000 | 斐讯 |
| `wndr3700v5` | 特殊布局 | Netgear |

#### 实际刷写流程（源码分析 + 抓包确认，2026-06-13）

```bash
# 1) 上传固件 + autoreboot=1（推荐，刷完自动重启）
POST /upload.html
  Content-Type: multipart/form-data
  fw_check=1  fw_file=@<固件>  flash_layout=reference
  fw_type=generic  autoreboot=1  submit=Upload
  → 响应: HTML 确认页（含 has_fw=1），服务端开始刷写

# 2) POST 轮询进度（每秒一次，ajax.js 用同步 POST）
POST /upgrade_query.html  Body: ""
  → 响应: 纯数字（进度 %），无 flash 时返回 "0"
  ★ 必须用 POST（ajax.js 源码确认: open("post", url, false)）

# 3) 进度到 100 → 自动重启（autoreboot=1 时）
#    无需手动 magic reboot！

# 4) 等待 30~90s 重启
#    成功信号: Server header 从 "Breed/1.0" 变成 uhttpd
#    /cgi-bin/luci 返回 403 + x-luci-login-required
```

**不传 autoreboot 时的手动重启流程**：
```bash
GET /reboot.html
  → HTML 含 <input name="magic" value="<动态值>">
  ★ magic 每次 GET 都不同，必须先 GET 再 POST

POST /rebooting.html
  submit=Reboot  magic=<动态值>
  → 302 → /
```

**⚠️ 关键陷阱**：
- `/upgrade_query.html` 必须用 **POST**，GET 也能拿数字但不触发 reboot 状态机
- `magic` 动态生成，不传 autoreboot 时必须**先 GET /reboot.html 再 POST**
- `autoreboot=1` 是最可靠的重启方式，避免 magic 提取失败

#### 下载：`GET /backup.html?type=<type>`

| type | 内容 |
|------|------|
| `eeprom` | Wi-Fi 校准（factory 分区，64K） |
| `full` | 完整 32MB flash dump |
| `firmware` | ❌ HTML 源码中已注释掉 |

#### 其他端点

| 端点 | 功能 |
|------|------|
| `GET /index.html` | 系统信息（CPU/RAM/Flash/频率） |
| `GET /clock.html` | CPU/DDR 频率设置 |
| `GET /envedit.html` | uboot env 任意读写（默认禁用） |
| `GET /envconf.html` | 预设字段写 env |
| `GET /reboot.html` | 手动重启 |
| `GET /reset.html` | 恢复出厂 |

## 已知固件

- **联想 Lecoo 官方固件**（出厂预装）：基于 OpenWrt 18.06 衍生，内核 3.14.79，版本 3.2.1.7437 (beta)，平台 ID `newifi-d2l`。默认 IP `192.168.99.1`，管理密码出厂为空，通过 ubus JSON-RPC (`POST /ubus`) 管理
- **OpenWrt** (主线): snapshot / 23.05 / 24.10 — `dts: mt7621_lenovo_newifi-d2.dts`
- **ImmortalWrt**: 基于 OpenWrt 的第三方发行

## 与小米机型的关键差异

| 维度 | 小米 AX 系列 | Newifi D2 |
|------|-------------|-----------|
| SoC 架构 | IPQ8071A (ARM) | MT7621 (MIPS) |
| Flash 类型 | SPI NAND (UBI) | SPI NOR (squashfs) |
| 双系统 | 是 (mtd12/mtd13) | 否 (单 firmware 分区) |
| bootloader | 官方 uboot | breed / 官方 uboot |
| 加密体系 | KEY/IV + SHA1/SHA256 | 无 (OpenWrt 原生) |
| 开 SSH | 漏洞注入 | 无需 (默认已开或 breed 直接刷) |

## 实测验证

### breed_enter.py（2026-06-10）

`breed_enter.py --iface enp0s26u1u1` 在用户机器上实机通过：

| 字段 | 实测值 |
|------|--------|
| 响应延迟 | 代码参数: 50ms 间隔, 每轮 5 包, 默认超时 180s |
| 路由器 IP | 192.168.1.1:37541（响应源） |
| 权限要求 | `sudo`（SO_BINDTODEVICE 需 CAP_NET_RAW） |
| 路由器硬件 | MT7621A ver 1, eco 3 / 512MB DDR3 / W25Q256 32MB / MT7530 |
| 路由器 Breed | 1.1 (r1237) [git-7ca77fe] 2018-10-14 |

### 5.breed_flash_firmware.py（2026-06-13）

`5.breed_flash_firmware.py --file files/immortalwrt-25.12.0-ramips-mt7621-d-team_newifi-d2-initramfs-kernel.bin` 实机通过：

| 字段 | 实测值 |
|------|--------|
| 固件 | immortalwrt-25.12.0 initramfs-kernel.bin (9.62MB) |
| MD5 | e1540a20f055a0e8ddadf7739f791c8b |
| 刷写耗时 | ~62s（POST 轮询 /upgrade_query.html） |
| autoreboot=1 | 刷完自动重启，无需手动 magic |
| 成功信号 | Server header 消失 + /cgi-bin/luci 403 + SSH dropbear |
