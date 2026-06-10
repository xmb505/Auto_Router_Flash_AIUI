# 小米 AX3600 刷机工具集

小米 AX3600 (R3600) 路由器刷机自动化工具。从出厂初始化到刷入自定义 uboot + 大分区的完整流程。

## 目标设备

| 项目 | 值 |
|------|-----|
| 型号 | 小米路由器 AX3600 (R3600) |
| SoC | IPQ8071A (Qualcomm) |
| 闪存 | 256MB SPI-NAND |
| 内存 | 512MB |
| 默认 IP | `192.168.31.1` / OpenWRT: `192.168.1.1` |
| 出厂默认密码 | `admin` |
| 固件版本 | `1.0.17` (实测) |
| SSH | `root / root` |

## NAND 分区布局（原厂）

```
mtd0:  0:SBL1       (1MB)    PBL/SBL
mtd1:  0:MIBIB      (1MB)    分区表 ← 刷大分区时替换
mtd2:  0:QSEE       (3MB)    TrustZone
mtd3:  0:DEVCFG     (512KB)  设备配置
mtd4:  0:RPM        (512KB)  Resource Power Manager
mtd5:  0:CDT        (512KB)  配置数据表
mtd6:  0:APPSBLENV  (512KB)  Uboot 环境变量
mtd7:  0:APPSBL     (1MB)    Uboot ← 刷自定义 uboot 时替换
mtd8:  0:ART        (512KB)  WiFi 校准数据
mtd9:  bdata        (512KB)  设备数据 (SN/MAC)
mtd10: crash        (512KB)  崩溃日志
mtd11: crash_syslog (512KB)  系统日志
mtd12: rootfs       (35.75MB) 主固件 (UBI: kernel + ubi_rootfs)
mtd13: rootfs_1     (35.75MB) 备份固件
mtd14: overlay      (31.5MB)  数据覆写 (UBI: data)
mtd15: rsvd0        (512KB)  保留
```

## 文件结构

```
.
├── auto_init.py         # 自动初始化向导（版本自适应）
├── check_init.sh        # 检测路由器初始化状态
├── check_version.sh     # 查看固件版本号
├── login_get_stok.py    # 登录获取 stok（SHA1，已初始化）
├── downgrade.py         # 固件降级/重刷
├── enable_ssh.py        # set_config_iotdev 注入开 SSH
├── rce.py               # 通用命令注入工具
├── rsh.py               # SSH/SCP 远程执行工具
├── flash_firmware.sh    # 刷写固件到备胎分区
├── control_openwrt.sh   # 过渡 OpenWRT 设置启动标志
├── flash_uboot.sh       # 刷入自定义 MIBIB + Uboot
├── uboot_upload.sh      # 通过 uboot web UI 上传固件
├── file/
│   ├── R3600_1.0.17.bin      # 降级固件（漏洞可用的版本）
│   ├── R3600_mtd12.bin       # OpenWRT 过渡固件 (36MB UBI 镜像)
│   └── openwrt/
│       ├── ax3600-mibib.bin  # 大分区表 (1MB)
│       └── ax3600-uboot.bin  # 自定义 uboot (628KB)
└── QWEN.md              # 本文件
```

## 刷机全流程

```
出厂初始化 → 降级 → 开SSH → 刷OpenWRT过渡固件
  → 设置启动标志 → 刷uboot+MIBIB → 断电重启
  → uboot web上传完整OpenWRT固件
```

### 阶段 1：出厂初始化

路由器初次通电或重置后，需先完成初始化向导。

```bash
./check_init.sh
python3 auto_init.py --admin-pwd 12345678
```

### 阶段 2：降级固件（如需）

```bash
python3 downgrade.py --pwd 12345678 --fw file/R3600_1.0.17.bin
```

### 阶段 3：获取 SSH 访问

```bash
python3 enable_ssh.py --pwd 12345678 --wait
# SSH: root@192.168.31.1 / 密码: root
```

### 阶段 4：刷入 OpenWRT 过渡固件

```bash
./flash_firmware.sh file/R3600_mtd12.bin
```

重启后 IP 变更为 **192.168.1.1**。

### 阶段 5：设置启动标志

```bash
./control_openwrt.sh
```

在过渡 OpenWRT 中设 `flag_last_success=0`, `flag_boot_rootfs=0`。

### 阶段 6：刷入 MIBIB + Uboot

```bash
./flash_uboot.sh
```

### 阶段 7：断电重启

新 uboot + 大分区表生效。

### 阶段 8：uboot web 上传固件

uboot 启动后 IP 为 **192.168.1.1**，通过浏览器或脚本上传：

```bash
./uboot_upload.sh file/xiaobai/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
```

上传后 uboot 自动刷写并重启，直接进入完整的 OpenWRT 系统。**不需要再做 sysupgrade**。

uboot 版本：`pepe2k/u-boot_mod v21.12.26`。

## 脚本说明

### check_init.sh — 检测初始化状态

```bash
./check_init.sh [IP]
# {"init":1} → 出厂未初始化
# {"init":0} → 已设置过
# {"init":-1,"error":…} → 不可达
```

### check_version.sh — 查看固件版本

```bash
./check_version.sh [IP]
# 输出: 1.0.17
```

### auto_init.py — 自动初始化

自动完成：登录 → DHCP → 禁用自动更新 → 设置 WiFi/管理密码。

```bash
python3 auto_init.py [--ip IP] [--ssid SSID] [--wifi-pwd PWD] [--admin-pwd PWD]
# {"stok":"...", "ip":"192.168.31.1", "ssid":"Xiaomi_20A4"}
```

**版本自适应**：检测 `romversion` 决定是否包含 `bw160` 字段。
- `1.0.x`：跳过 `bw160`
- `1.1.x`及更高：包含 `bw160=false`

### login_get_stok.py — 登录获取 stok

```bash
python3 login_get_stok.py [--ip IP] [--pwd PWD]
# {"stok":"..."}
```

SHA1 双哈希，GET 方式，适用于已初始化状态。

### downgrade.py — 固件降级

```bash
python3 downgrade.py --fw file/R3600_1.0.17.bin
python3 downgrade.py --pwd 12345678 --fw file/R3600_1.0.17.bin
```

流程：上传固件 → syslock → flash_permission → flash_rom → 重启

### enable_ssh.py — 注入开 SSH

```bash
python3 enable_ssh.py --pwd 12345678 --wait
```

利用 `set_config_iotdev` 的 `ssid` 参数注入 4 条命令：

```
1. nvram set flag_last_success=0; flag_boot_rootfs=0; boot_wait=on;
   uart_en=1; telnet_en=1; ssh_en=1; nvram commit
2. sed -i 's/channel=.*/channel="debug"/g' /etc/init.d/dropbear
3. echo -e 'root\nroot' > /tmp/psw.txt; passwd root < /tmp/psw.txt
4. /etc/init.d/dropbear restart
```

无需重启，SSH 秒级就绪。

### rce.py — 通用命令注入

```bash
python3 rce.py --pwd 12345678 'cat /proc/version'
python3 rce.py --stok-only --pwd 12345678
```

### rsh.py — SSH/SCP 远程执行

```bash
python3 rsh.py run "命令"
python3 rsh.py put 本地文件 远程路径
python3 rsh.py get 远程路径 本地文件
```

默认 host=192.168.31.1, user=root, pwd=root。

### flash_firmware.sh — 刷写固件到备胎分区

```bash
./flash_firmware.sh file/R3600_mtd12.bin
```

上传 → MD5 → 写入非活跃分区 → 切换 nvram 启动标志 → 重启。

### control_openwrt.sh — 过渡 OpenWRT 设置启动标志

```bash
./control_openwrt.sh
```

在过渡 OpenWRT (192.168.1.1) 上执行 `fw_setenv`，为刷 uboot/MIBIB 做准备。

### flash_uboot.sh — 刷入自定义 MIBIB + Uboot

```bash
./flash_uboot.sh
```

上传 → MD5 → 擦除写入 mtd1 (MIBIB) → 擦除写入 mtd7 (APPSBL) → 需断电重启。

### uboot_upload.sh — 通过 uboot web UI 上传固件

```bash
./uboot_upload.sh /path/to/firmware.bin
```

通过 curl 模拟浏览器 POST multipart/form-data 到 `http://192.168.1.1/`，字段名 `firmware`。

## 密码学

### 常量

| 常量 | 值 |
|------|-----|
| KEY | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| IV | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |

### 登录密码

```python
inner    = SHA1(admin_pwd + KEY)             # SHA1 hex
password = SHA1(nonce + inner)               # SHA1 hex
```

nonce 格式：`0__{秒级时间戳}_{随机0-9999}`

### newPwd（set_router_normal）

```python
aes_key  = SHA1(old_pwd + KEY)[:32]          # 16 bytes
plain    = SHA1(new_pwd + KEY).hex.encode()  # UTF-8 bytes
newPwd   = AES_CBC_encrypt(plain, aes_key, IV, PKCS7)  # Base64
```

## SSH 连接

```bash
# 小米原厂固件 (192.168.31.1)
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1

# 过渡 OpenWRT (192.168.1.1)
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.1.1
```

路由器只提供 `ssh-rsa` host key，需显式指定算法。过渡 OpenWRT 通常为免密登录。

## 已知约定

- **JSON 输出** — 所有 Python 脚本 stdout 输出纯 JSON，stderr 输出进度
- **出错退出码** — 失败 exit 1，成功 exit 0
- **argparse** — 所有 Python 脚本支持 `--help`
- **依赖** — `auto_init.py` 需 `pycryptodome`；`rsh.py`/`flash_firmware.sh`/`flash_uboot.sh` 需 `sshpass`；其余纯标准库

## 参考

- [AX3000T 刷机工具集](../AX3000T/QWEN.md) — 同项目的 MediaTek 平台参考实现
