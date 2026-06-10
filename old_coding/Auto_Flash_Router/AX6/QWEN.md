# Redmi AX6 刷机工具集

Redmi AX6 (RA69) 路由器刷机自动化工具。从出厂初始化到开启 SSH 的完整流程。

> **注意**: AX6 是 **Redmi 版 AX3600**（同 IPQ807x 平台），但 SSH 开启方式完全不同！AX6 **不能**使用 `set_config_iotdev` 注入，必须通过辅助路由器 WiFi 漏洞开启 SSH。

## 目标设备

| 项目 | 值 |
|------|------|
| 型号 | Redmi 路由器 AX6 (RA69) |
| SoC | IPQ8071A (Qualcomm) |
| 闪存 | 256MB SPI-NAND |
| 内存 | 512MB |
| 默认 IP | `192.168.31.1` |
| 出厂默认密码 | `admin` |
| 固件版本 | `1.0.16` (降级后) / `1.1.10` (原厂) |

## 文件结构

```
.
├── check_init.sh            # 检测路由器初始化状态
├── check_version.sh         # 查看固件版本号
├── auto_init.py             # 自动完成初始化向导 (SHA1)
├── login_get_stok.py        # 登录获取 stok
├── downgrade.py             # 固件降级
├── enable_ssh.py            # 辅助路由器 WiFi 注入开 SSH
├── get_wifi_password.py     # 获取 5GHz WiFi 密码（= SSH 密码）
├── exploit_server.py        # Alpine 端漏洞投送 HTTP 服务器
├── files/
│   └── RA69_1.0.16.bin     # 降级固件（漏洞可用版本）
└── unlock-redmi-ax3000/     # 第三方开源利用脚本 (yyjdelete/Robert Marko/Tianling Shen)
```

## 漏洞原理（MEDIATEK-ARM-IS-GREAT）

AX6 原生小米固件硬编码了一组 mesh 组网凭据（SSID `MEDIATEK-ARM-IS-GREAT`, 密码 `ARE-YOU-OK`），并开放了 `extendwifi_connect` + `oneclick_get_remote_token` API 用于 mesh 节点从主路由获取管理 token。

攻击链：

```
攻击机                   辅助路由 (Alpine/OpenWrt)         AX6 (Redmi)
  │                            │                           │
  │  ① login 获取 stok        │                           │
  │━━━━━━━━━━━━━━━━━━━━━━━━━━▶│                           │
  │                            │                           │
  │  ② extendwifi_connect     │                           │
  │  通知 AX6 连入辅助 WiFi   │                           │
  │━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶│
  │                            │                           │
  │                            │◄━━━━━━━ ③ 回连辅助WiFi ───┤
  │                            │                           │
  │  ④ oneclick_get_remote_token                          │
  │━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶│
  │                            │                           │
  │                            │◄━ ⑤ 回调 /api/xqsystem/  ─┤
  │                            │     token (GET/POST)      │
  │                            │                           │
  │                            │── ⑥ 返回恶意 token ──────▶│
  │                            │    ("; nvram set ...")    │
  │                            │                           │
  │                            │          ⑦ eval 执行 → SSH 开启
```

关键点：
- `extendwifi_connect` 让 AX6 **主动** 连接辅助 WiFi
- 辅助路由关闭 DHCP，AX6 会落到 `169.254.x.x` 链路本地 IP
- AX6 mesh 协议**硬编码**回调地址为 `169.254.31.1`（不是从 DHCP/路由推算的）
- 辅助路由在该 IP 上监听 80 端口返回恶意 token（shell 命令）
- AX6 对回调 token 做 `eval` → 命令注入成功 → SSH 开启

## 开启 SSH 全流程

### 阶段 0：准备辅助路由

**方式 A — OpenWrt 路由器（传统方式）：**

在带无线网卡的 OpenWrt 路由器上运行 `unlock-redmi-ax3000/wireless.sh`，它会自动：
1. 创建 LuCI `/api/xqsystem/token` 端点返回恶意 token
2. 建 WiFi（SSID `MEDIATEK-ARM-IS-GREAT`, 密码 `ARE-YOU-OK`）
3. 关闭 DHCP，设 LAN IP `169.254.31.1`

```bash
# 在辅助路由器上执行
bash unlock-redmi-ax3000/wireless.sh
```

**方式 B — 分离式（本项目推荐）：**

辅助路由器只做 WiFi（不开 DHCP），Alpine 服务器单独投送 token。

```bash
# 1. 辅助路由器：建一个不加密或已知密码的 WiFi
#    SSID: AX6-EXPLOIT, 密码: 12345678
#    关闭 DHCP

# 2. Alpine 上启动 exploit 服务器（纯 Python 3 标准库）
python3 exploit_server.py
# 默认监听 0.0.0.0:80
# Alpine 需配置 169.254.31.1 地址：
ip addr add 169.254.31.1/16 dev eth0
```

### 阶段 1：检测与初始化

```bash
# Step 1: 检测出厂状态
bash check_init.sh
# {"init":1} → 出厂未初始化，走 Step 2
# {"init":0} → 已初始化，跳 Step 3

# Step 2: 出厂初始化（如需）
python3 auto_init.py --admin-pwd 12345678
```

### 阶段 2：降级固件（如需）

部分固件版本可能缺少 `extendwifi_connect` API，需降级到可用版本。

```bash
# 查看当前版本
bash check_version.sh

# 如需降级 1.0.16
stok=$(python3 login_get_stok.py --pwd 12345678 | python3 -c "import json,sys; print(json.load(sys.stdin)['stok'])")
python3 downgrade.py --stok "$stok" --fw files/RA69_1.0.16.bin
# 路由器将重启，等待就绪
```

### 阶段 3：WiFi 注入开 SSH

```bash
# Step 1: 登录获取 stok
stok=$(python3 login_get_stok.py --pwd 12345678 | python3 -c "import json,sys; print(json.load(sys.stdin)['stok'])")

# Step 2: 触发攻击链（extendwifi_connect → oneclick_get_remote_token）
python3 enable_ssh.py --stok "$stok"
# {"extendwifi_code": 0, "token_result": {"code": 0, ...}}

# Step 3: 获取 SSH 密码
python3 get_wifi_password.py --stok "$stok"
# {"band": "5G", "password": "544e201c"}
```

### 阶段 4：SSH 连接

```bash
sshpass -p '544e201c' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 或一条龙
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 密码: 5GHz WiFi 密码
```

### 全自动一条龙

```bash
cd AX6
stok=$(python3 login_get_stok.py --pwd 12345678 | python3 -c "import json,sys; print(json.load(sys.stdin)['stok'])")
python3 enable_ssh.py --stok "$stok"
pwd=$(python3 get_wifi_password.py --stok "$stok" | python3 -c "import json,sys; print(json.load(sys.stdin)['password'])")
sshpass -p "$pwd" ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

## 密码学

AX6 与 AX3600 相同，使用 `newEncryptMode=0`（SHA1 旧版加密）。

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

### 固件版本自适应

版本 >= `1.1.x` 需要在初始化时带 `bw160=false` 字段；`1.0.x` 不能带此字段。

```python
# auto_init.py 中自动检测
has_bw160 = version >= "1.1"
```

## 与 AX3600 的关键差异

| 特性 | AX6 (RA69) | AX3600 (R3600) |
|------|-----------|----------------|
| SSH 开启方式 | 辅助路由器 WiFi 注入 | `set_config_iotdev` 命令注入 |
| SSH 密码 | 5GHz WiFi 密码（需从前端读取） | `root`（固定） |
| 是否需要辅助路由 | 是（必须） | 否 |
| 是否需要降级 | 部分版本需要 | 部分版本需要 |
| 加密模式 | `newEncryptMode=0` (SHA1) | `newEncryptMode=0` (SHA1) |
| API 基线 | 完全兼容 | — |

## 脚本说明

### check_init.sh — 检测初始化状态

```bash
bash check_init.sh [IP]
# {"init":1} → 出厂未初始化
# {"init":0} → 已设置过
```

### auto_init.py — 初始化向导自动化

```bash
python3 auto_init.py [--ip IP] [--ssid SSID] [--wifi-pwd PWD] [--admin-pwd PWD]
# {"stok":"...", "ip":"192.168.31.1", "ssid":"Xiaomi_20A4"}
```

### login_get_stok.py — 登录获取 stok

```bash
python3 login_get_stok.py [--ip IP] [--pwd PWD]
# {"stok":"..."}
```

### downgrade.py — 固件降级

```bash
python3 downgrade.py --stok STOK --fw files/RA69_1.0.16.bin
```

4 步流程：上传固件 → syslock → flash_permission → flash_rom → 重启。

### enable_ssh.py — 辅助路由器注入开 SSH

```bash
python3 enable_ssh.py --stok STOK
# [1/2] 连接辅助 WiFi
# [2/2] 触发 AX6 回调拿 token
```

### get_wifi_password.py — 获取 SSH 密码

```bash
python3 get_wifi_password.py --stok STOK
# {"band": "5G", "password": "544e201c"}
```

通过 `/api/xqnetwork/wifi_detail_all` API 获取 5GHz WiFi 密码，该密码即为 SSH 密码。

### exploit_server.py — Alpine 端漏洞投送服务器

```bash
python3 exploit_server.py [--port 80] [--payload '; cmd;']
```

- 纯 Python 3 标准库，适合 Alpine 等精简系统
- 端点 `GET/POST /api/xqsystem/token`
- AX6 会带 `/cgi-bin/luci/` 前缀回调，脚本使用 `endswith` 匹配
- 支持自定义 payload

## 刷入自定义 MIBIB + Uboot

从 **OpenWRT/ImmortalWrt** 中（非 stock 固件）刷写，mtd 设备是解锁的。

```bash
# 上传文件到 /tmp
scp -O files/openwrt/ax6-mibib-stock.bin root@192.168.1.1:/tmp/
scp -O files/openwrt/ax6-uboot-stock.bin root@192.168.1.1:/tmp/

# 刷写
ssh root@192.168.1.1 '
mtd erase /dev/mtd1
mtd write /tmp/ax6-mibib-stock.bin /dev/mtd1
mtd verify /tmp/ax6-mibib-stock.bin /dev/mtd1

mtd erase /dev/mtd7
mtd write /tmp/ax6-uboot-stock.bin /dev/mtd7
mtd verify /tmp/ax6-uboot-stock.bin /dev/mtd7
sync
'
```

或使用自带脚本：

```bash
bash flash_uboot.sh
```

（脚本运行后需**拔电重启**进入新 uboot，不能 `reboot`）

## 刷入 OpenWRT 固件（从 stock 到 OpenWRT）

必须在刷 MIBIB+uboot **之前**完成，因为需要从 stock 分区锁中跳出。

```bash
# 1. 确认当前启动分区
nvram get flag_boot_rootfs
# 0=rootfs, 1=rootfs_1

# 2. 确定空闲分区，写入 OpenWRT
# 例如当前在 rootfs_1 (flag=1)，则写 mtd12 (rootfs)
ubiformat /dev/mtd12 -y -f files/openwrt/immortalwrt-24.10.6-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi

# 3. 切启动标志到写入的分区
nvram set flag_last_success=0
nvram set flag_boot_rootfs=0
nvram commit

# 4. 重启（IP 变为 192.168.1.1）
reboot
```

> **关键**：必须用 `ubiformat` 而非 `mtd write` 写入 UBI 镜像。`mtd write` 不会正确初始化 UBI 卷表，无法启动。

### uboot web UI 进入方式

新 uboot（pepe2k `u-boot_mod` 风格）内置 HTTP 固件上传页面。

1. **拔掉电源**
2. **按住 Reset 键不放**
3. **插上电源**，继续按住 Reset
4. 等待指示灯变为 **蓝色**（约 3-5 秒）→ 松开
5. 电脑设静态 IP `192.168.1.10/24`
6. 浏览器访问 `http://192.168.1.1/`
7. 选择 `.ubi` 文件上传，等待刷写完成自动重启

> 蓝色灯亮 = uboot 的 HTTPD 已启动，可以进 web 刷机页面。

## SSH 连接

```bash
sshpass -p '<5G密码>' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

路由器只提供 `ssh-rsa` host key，需显式指定算法。

### 文件说明

| 文件 | 路径 | 用途 |
|------|------|------|
| ImmortalWrt 过渡固件 | `files/openwrt/immortalwrt-24.10.6-...-factory.ubi` | 刷入空闲 rootfs 分区，用于过渡进入 OpenWRT |
| 最终固件 | `files/xiaobai/libwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi` | uboot web UI 上传，刷完后直入 OpenWRT |
| 自定义 MIBIB | `files/openwrt/ax6-mibib-stock.bin` | 在 OpenWRT 内刷入 mtd1 |
| 自定义 uboot | `files/openwrt/ax6-uboot-stock.bin` | 在 OpenWRT 内刷入 mtd7 |

## 已知约定

- **JSON 输出** — 所有 Python 脚本 stdout 输出纯 JSON，stderr 输出进度
- **出错退出码** — 失败 exit 1，成功 exit 0
- **argparse** — 所有 Python 脚本支持 `--help`
- **依赖** — `auto_init.py` 需 `pycryptodome`；`downgrade.py`/`enable_ssh.py`/`get_wifi_password.py` 纯标准库；`flash_*` shell 脚本需 `sshpass`；`check_*` shell 脚本需 `curl` + `python3`
- **UNIX 哲学** — 每个脚本只做一件事，`login_get_stok.py` 专司登录，其他脚本通过 `--stok` 参数传令牌
