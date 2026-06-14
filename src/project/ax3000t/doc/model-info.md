# AX3000T 硬件信息 (Model Info)

## 目标设备

| 项目 | 值 |
|------|-----|
| 型号 | 小米路由器 AX3000T (RD03) |
| SoC | MediaTek Filogic 820 (MT7981BA) |
| 闪存 | 128MB SPI-NAND |
| 默认 IP | `192.168.31.1` (stock) / `192.168.1.1` (uboot/OpenWrt) |
| 出厂密码 | `admin` |
| 加密模式 | `newEncryptMode=1` (SHA256) |
| 固件版本 | `1.0.64` (实测) |
| 降级固件 | `RD03_1.0.47.bin` |

## NAND 分区布局

```
mtd0: spi0.0       (128MB)  整个 SPI-NAND
mtd1: BL2          (1MB)    预引导 (PBL/SBL)
mtd2: Nvram        (256KB)  NVRAM 配置
mtd3: Bdata        (256KB)  设备信息 (SN/MAC)
mtd4: Factory      (2MB)    WiFi 校准
mtd5: FIP          (2MB)    uboot (FIP FIT image) ← 步骤 5 刷写目标
mtd6: crash        (256KB)  崩溃日志
mtd7: crash_log    (256KB)  崩溃日志
mtd8: ubi          (34MB)   主固件
mtd9: ubi1         (34MB)   备份固件
mtd10: overlay     (32MB)   数据覆写
mtd11: data        (12MB)   用户数据
mtd12: KF          (256KB)  保留
```

## 密码学常量

| 常量 | 值 |
|------|-----|
| KEY | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| IV | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |
| 加密模式 | `newEncryptMode=1` (SHA256) |

⚠️ KEY/IV 优先从路由器运行时扒取（`init.<hash>.js`），不在代码里写死。
已知常量仅作为扒取失败时的回退。

## 与 AX5/AX6 的差异

| 维度 | AX5/AX6 | AX3000T |
|------|---------|---------|
| SoC | Qualcomm IPQ6000/IPQ807x | MediaTek MT7981 |
| 加密 | SHA1 (newEncryptMode=0) | SHA256 (newEncryptMode=1) |
| 登录 | GET + SHA1 | POST + SHA256 |
| SSH 注入 | set_config_iotdev ssid | start_binding key |
| 刷机方式 | ubiformat mtd18/mtd19 | mtd write FIP + TFTP recovery |
| OpenWrt IP | 192.168.1.1 | 192.168.1.1 (uboot 后) |

## 固件文件

| 文件 | 用途 | 大小 |
|------|------|------|
| `RD03_1.0.47.bin` | 降级固件 | ~23MB |
| `immortalwrt-25.12.0-...-bl31-uboot.fip` | 自定义 uboot (FIP) | ~800KB |
| `immortalwrt-...-initramfs-recovery.itb` | TFTP recovery 拉取用 initramfs | ~13MB |
| `immortalwrt-...-squashfs-sysupgrade.itb` | 完整 OpenWrt sysupgrade | ~16MB |

## SSH 连接

```bash
# stock 固件侧（步骤 4 注入后）
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1

# OpenWrt 侧（步骤 6/7 后）
ssh root@192.168.1.1  # 默认空密码
```

路由器只提供 `ssh-rsa` host key，需显式指定算法。
