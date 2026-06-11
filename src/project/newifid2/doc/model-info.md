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
| 默认 IP | `192.168.1.1` |
| 默认子网 | `255.255.255.0` |
| 默认 SSH | OpenWrt: root (无密码) / PandoraBox: root/admin |
| 默认 Wi-Fi | OpenWrt: 关闭 / PandoraBox: Newifi_XXXX |

## 刷机方式

| 方法 | 适用固件 | 说明 |
|------|---------|------|
| ** breed Web 恢复** | 任何 | 按住 reset 上电 → `192.168.1.1` → 网页上传 |
| ** mtd write** | OpenWrt sysupgrade | SSH 进系统后 `mtd write <file> firmware` |
| ** sysupgrade** | OpenWrt sysupgrade | `sysupgrade -n <file>` (保留/清空配置) |
| ** TFTP 恢复** | breed 下可用 | breed 内置 TFTP 客户端 |

## Breed Bootloader

Newifi D2 最常见的第三方 bootloader 是 **breed** (由 hackpascal 开发)：
- 按住 Reset 上电 → LED 闪烁 → 浏览器打开 `192.168.1.1`
- 支持 Web 上传刷机、环境变量编辑、EEPROM 备份
- 进入 breed 后可通过 `breed Enter` 命令进入命令行

## 已知固件

- **OpenWrt** (主线): snapshot / 23.05 / 24.10 — `dts: mt7621_lenovo_newifi-d2.dts`
- **ImmortalWrt**: 基于 OpenWrt 的第三方发行
- **Padavan**: 老毛子固件 (MT7621 版)
- **PandoraBox**: 原厂固件 (已停止更新)

## 与小米机型的关键差异

| 维度 | 小米 AX 系列 | Newifi D2 |
|------|-------------|-----------|
| SoC 架构 | IPQ8071A (ARM) | MT7621 (MIPS) |
| Flash 类型 | SPI NAND (UBI) | SPI NOR (squashfs) |
| 双系统 | 是 (mtd12/mtd13) | 否 (单 firmware 分区) |
| bootloader | 官方 uboot | breed / 官方 uboot |
| 加密体系 | KEY/IV + SHA1/SHA256 | 无 (OpenWrt 原生) |
| 开 SSH | 漏洞注入 | 无需 (默认已开或 breed 直接刷) |

## 实测验证（2026-06-10）

`breed_enter.py --iface enp0s26u1u1` 在用户机器上实机通过：

| 字段 | 实测值 |
|------|--------|
| 响应延迟 | 21.01s（43 次 × 500ms） |
| 路由器 IP | 192.168.1.1:37541（响应源） |
| 权限要求 | `sudo`（SO_BINDTODEVICE 需 CAP_NET_RAW） |
| 路由器硬件 | MT7621A ver 1, eco 3 / 512MB DDR3 / W25Q256 32MB / MT7530 |
| 路由器 Breed | 1.1 (r1237) [git-7ca77fe] 2018-10-14 |

`breed_flash` 也实机通过：上传 `immortalwrt-ramips-mt7621-d-team_newifi-d2-squashfs-sysupgrade.bin` 17.3MB 成功，flash 100% 后自动重启到 ImmortalWrt，LuCI 在 `/cgi-bin/luci`（403 + `x-luci-login-required: yes`）。
