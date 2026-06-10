# Redmi AX5 刷机工具集

红米 AX5 (RA67 / RM1800) 路由器刷机自动化工具。从检测状态到刷入大分区 OpenWrt 的完整流程。

## 目标设备

| 项目 | 值 |
|------|-----|
| 型号 | 红米 AX5 (RA67 / RM1800) |
| SoC | IPQ6000 (Qualcomm) |
| 闪存 | 128MB SPI-NAND |
| 内存 | 256MB |
| 默认 IP | `192.168.31.1` |
| uboot IP | `192.168.1.1` |
| 出厂默认密码 | `admin` |

## 文件结构

```
.
├── check_init.sh           # 检测路由器初始化状态
├── auto_init.py            # 自动完成初始化向导
├── login_get_stok.py       # 登录获取 stok
├── downgrade.py            # 降级固件
├── enable_ssh.py           # 命令注入开 SSH
├── rsh.py                  # SSH/SCP 远程执行工具
├── doc/
│   └── check_init_logic.md # 密码学 + 刷机全流程文档
├── files/
│   ├── RA67_1.0.26.bin     # 降级固件（漏洞可用的版本）
│   ├── RA67_1.0.49.bin     # 新版固件
│   └── tmp/
│       ├── xiaomi-rm1800-mibib.bin     # 大分区表 (1MB)
│       ├── xiaomi-rm1800-u-boot.mbn    # 自定义 uboot (596KB)
│       ├── libwrt-*-factory.ubi        # 大分区 OpenWrt 固件
│       └── flash.sh                    # uboot 刷写脚本（参考用）
└── QWEN.md
```

## 刷机全流程

### 阶段 1：获取 SSH 访问

```
检测状态 → 初始化(如需) → 降级 → 开SSH
```

```bash
# Step 1: 检测状态
./check_init.sh
# {"init":1} → 走 Step 2a
# {"init":0} → 走 Step 2b

# Step 2a: 自动初始化（出厂状态）
python3 auto_init.py --admin-pwd 12345678

# Step 2b: 登录获取 stok（已初始化）
python3 login_get_stok.py --pwd 12345678

# Step 3: 降级到 1.0.26
python3 downgrade.py --stok STOK --fw files/RA67_1.0.26.bin

# Step 4: 命令注入开 SSH
python3 enable_ssh.py --stok STOK --local-ip 本机IP --wait
# SSH: root@192.168.31.1 / password
```

### 阶段 2：刷入自定义 uboot

```bash
# 上传 uboot → 刷入 → 重启进 uboot
python3 rsh.py --host 192.168.31.1 --user root --pwd password put \
    files/tmp/xiaomi-rm1800-u-boot.mbn /tmp

python3 rsh.py --host 192.168.31.1 --user root --pwd password run \
    'mtd write /tmp/xiaomi-rm1800-u-boot.mbn /dev/mtd7'

python3 rsh.py --host 192.168.31.1 --user root --pwd password run \
    'nvram set ssh_en=1 && nvram set uart_en=1 && nvram set boot_wait=on && \
     nvram set bootcmd=bootipq && nvram set ipaddr=192.168.1.1 && \
     nvram set serverip=192.168.1.10 && nvram commit'

python3 rsh.py --host 192.168.31.1 --user root --pwd password run 'reboot'
```

### 阶段 3：uboot web UI 刷入大分区 + 固件

重启后路由器进入 uboot，电脑改 IP 为 `192.168.1.10`，浏览器访问 `http://192.168.1.1/`。

通过 uboot 网页界面：
1. 刷写 `xiaomi-rm1800-mibib.bin`（分区表）
2. 刷写 `libwrt-*-factory.ubi`（固件）
3. 重启 → 大分区 OpenWrt 启动

## 脚本说明

### check_init.sh — 检测初始化状态

```bash
./check_init.sh [IP]
# {"init":1}          → 出厂未初始化
# {"init":0}          → 已设置过
# {"init":-1,"error":…} → 不可达
```

原理：访问 `/cgi-bin/luci/web` 检查 302 重定向目标是否指向 `/init.html`。

### auto_init.py — 初始化向导自动化

```bash
python3 auto_init.py [--ip IP] [--ssid SSID] [--wifi-pwd PWD] [--admin-pwd PWD]
# {"stok":"...", "ip":"192.168.31.1", "ssid":"Redmi_7D5A"}
```

自动完成：登录 → DHCP → 禁用更新 → 设置 WiFi/管理密码。

### login_get_stok.py — 登录获取 stok

```bash
python3 login_get_stok.py [--ip IP] [--pwd PWD]
# {"stok":"..."}
```

### downgrade.py — 降级固件

```bash
python3 downgrade.py --stok STOK --fw files/RA67_1.0.26.bin
# {"stok":"...", "downgrade":true, "firmware":"..."}
```

通过 `upload_rom` + `flash_rom` API 完成。上传为 `multipart/form-data`，字段名 `image`。

### enable_ssh.py — 命令注入开 SSH

```bash
python3 enable_ssh.py [--stok STOK] --local-ip 本机IP [--wait]
# {"stok":"...", "inject_ok":true, "ssh_user":"root", "ssh_pwd":"password"}
```

利用 `set_config_iotdev` 的 `ssid` 参数命令注入，远程执行 `curl .../unlock_ssh.sh | ash`。

### rsh.py — SSH/SCP 远程执行

```bash
python3 rsh.py --host HOST --user root --pwd PASSWORD run "命令"
python3 rsh.py --host HOST --user root --pwd PASSWORD put 本地文件 远程路径
python3 rsh.py --host HOST --user root --pwd PASSWORD get 远程路径 本地文件
```

基于 **sshpass + 系统 OpenSSH**。兼容路由器老旧加密算法（`ssh-rsa` host key）。

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

### newPwd（set_router_normal）

```python
aes_key  = SHA1(old_pwd + KEY)[:32]          # 16 bytes
plain    = SHA1(new_pwd + KEY).hex.encode()  # UTF-8 bytes
newPwd   = AES_CBC_encrypt(plain, aes_key, IV, PKCS7)  # Base64
```

nonce 格式：`0__{秒级时间戳}_{随机0-9999}`

## 已知约定

- **JSON 输出** — 所有脚本 stdout 输出纯 JSON，stderr 输出进度/错误
- **出错退出码** — 失败 exit 1，成功 exit 0
- **argparse** — 所有 Python 脚本支持 `--help`
- **依赖** — `auto_init.py` 需 `pycryptodome`；`rsh.py` 需 `sshpass`；其余纯 Python 标准库
- **MTD 写入** — 推荐用 `/dev/mtdX` 而非分区名，避免冒号被 shell 解析
- **MIBIB 锁定** — 分区表（mtd1）在系统内无法写入，必须通过 uboot web UI 刷
