# 红米 AX5 文档

## 脚本索引

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `check_init.sh` | 检测初始化状态 | curl |
| `auto_init.py` | 自动完成初始化向导 | pycryptodome |
| `login_get_stok.py` | 登录获取 stok | — |
| `downgrade.py` | 降级固件 | — |
| `enable_ssh.py` | 命令注入开 SSH | — |
| `rsh.py` | SSH/SCP 远程执行 | sshpass |

---

# 检测逻辑：check_init.sh

## 概述

```bash
./check_init.sh [路由器IP]
# {"init":1}          → 出厂初始化
# {"init":0}          → 正常模式
# {"init":-1,"error":…}  → 不可达
```

判断路由器是否处于出厂初始化状态。

## 原理

LuCI 后端收到 `/cgi-bin/luci/web` 请求时，检测系统是否已初始化：

```
访问 192.168.31.1
  └─ /cgi-bin/luci/web
        ├─ 未初始化 → 302 Location: /init.html
        └─ 已初始化 → 302 Location: /cgi-bin/luci/web/home
```

通过检查 302 重定向目标判断状态。

## 脚本

```bash
#!/bin/bash
ROUTE_IP="${1:-192.168.31.1}"
LOCATION=$(curl -s --connect-timeout 3 -o /dev/null \
    -w '%{redirect_url}' "http://${ROUTE_IP}/cgi-bin/luci/web")

if [[ -z "$LOCATION" ]]; then
    echo '{"init":-1,"error":"路由器不可达"}'
elif [[ "$LOCATION" == *"/init.html"* ]]; then
    echo '{"init":1}'
else
    echo '{"init":0}'
fi
```

---

# 密码学分析

## 常量

| 常量 | 值 | 用途 |
|------|-----|------|
| KEY | `a2ffa5c9be07488bbb04a3a47d3c5f6a` | SHA1 盐值、AES 密钥 |
| IV | `64175472480004614961023454661220` | AES-CBC 初始向量 |
| 出厂密码 | `admin` | 默认管理员密码（不是空） |

## Nonce

```python
nonce = f"0__{秒级时间戳}_{随机0-9999}"
# 示例: 0__1779787534_2678
```

## 登录密码

```python
inner    = SHA1(admin_pwd + KEY)        # SHA1 hex
password = SHA1(nonce + inner)          # SHA1 hex
```

## newPwd（set_router_normal）

```python
aes_key  = SHA1(old_pwd + KEY)[:32]     # 16 字节
plain    = SHA1(new_pwd + KEY).hex      # UTF-8 字符串，非 hex 解码
newPwd   = AES_CBC(plain, aes_key, IV, PKCS7)  # Base64 输出
```

## 示例

`admin_pwd="12345678"`, `old_pwd="admin"`:

```
SHA1("admin" + KEY)     = 5717b132b467f8dd28a03cab7dc8653f1c267e6a
AES key                 = 5717b132b467f8dd28a03cab7dc8653f
SHA1("12345678" + KEY)  = a671b7ae34ff1ad9bc001f572e0648ef47fe6e0a
newPwd (Base64)         = GxXairsjm7UiFHzLJc11aHdx5W6Uhq2eXWaj0DLr/O5eVEyk8XhZ85EVTS0p/tlM
```

---

# 刷机完整流程

## 阶段 1：获取 SSH

```
检测 → 初始化(如需要) → 降级 → 开SSH
```

```bash
# 检测状态
./check_init.sh
# {"init":1} → python3 auto_init.py --admin-pwd 12345678

# 获取 stok
python3 login_get_stok.py --pwd 12345678

# 降级到 1.0.26
python3 downgrade.py --stok STOK --fw files/RA67_1.0.26.bin

# 开 SSH（chfs 需先运行在 80 端口，提供 unlock_ssh.sh）
python3 enable_ssh.py --local-ip 本机IP --stok STOK --wait
```

## 阶段 2：刷入自定义 uboot

```bash
# 上传 uboot
python3 rsh.py --host 192.168.31.1 --user root --pwd password put \
    files/tmp/xiaomi-rm1800-u-boot.mbn /tmp

# 刷 uboot + 设 nvram
python3 rsh.py --host 192.168.31.1 --user root --pwd password run \
    'mtd write /tmp/xiaomi-rm1800-u-boot.mbn /dev/mtd7'

python3 rsh.py --host 192.168.31.1 --user root --pwd password run \
    'nvram set bootcmd=bootipq && nvram set ipaddr=192.168.1.1 && \
     nvram set serverip=192.168.1.10 && nvram commit'

# 重启进 uboot
python3 rsh.py --host 192.168.31.1 --user root --pwd password run 'reboot'
```

> **注意**: 官方系统内只能刷 uboot，MIBIB 分区被锁定。重启后通过 uboot 的 HTTPD 网页刷写 MIBIB + 固件。

## 阶段 3：uboot web UI 刷大分区

重启后：
1. 电脑 IP 改为 `192.168.1.10`
2. 浏览器访问 `http://192.168.1.1/`
3. 通过网页刷写 `xiaomi-rm1800-mibib.bin` → `libwrt-*-factory.ubi`
4. 重启 → 大分区 OpenWrt

---

# API 参考

## 初始化阶段 (init=1)

| 步骤 | Method | 端点 |
|------|--------|------|
| 登录 | GET | `api/xqsystem/login` |
| DHCP | GET | `api/xqnetwork/set_wan_new` |
| 禁用更新 | GET | `api/misystem/vas_switch` |
| 设置密码 | POST | `api/misystem/set_router_normal` |

## 正常模式 (init=0)

| 步骤 | Method | 端点 |
|------|--------|------|
| 登录 | GET | `api/xqsystem/login` |

## 固件操作

| 步骤 | Method | 端点 | 格式 |
|------|--------|------|------|
| 上传固件 | POST | `uploadfile/cgi-bin/luci/;stok=xxx/api/xqsystem/upload_rom` | multipart/form-data, field: `image` |
| 触发刷写 | GET | `api/xqsystem/flash_rom` | `custom=1&recovery=1` |
| 命令注入 | GET | `api/misystem/set_config_iotdev` | `ssid` 参数含 shell 命令 |

---

# MTD 分区参考

## 官方布局

| mtd | 名称 | 大小 | 备注 |
|-----|------|------|------|
| 0 | 0:SBL1 | 1.5MB | |
| 1 | 0:MIBIB | 1MB | 分区表，系统内锁定 |
| 2 | 0:QSEE | 3.5MB | 安全世界 |
| 3-6 | DEVCFG/RPM/CDT/APPSBLENV | 各512KB | |
| 7 | 0:APPSBL | 1.5MB | uboot，可刷写 |
| 8 | 0:ART | 512KB | 射频校准 |
| 9-11 | bdata/crash/crash_syslog | 各512KB | |
| 12-13 | BOOTCONFIG/BOOTCONFIG1 | 各512KB | |
| 14-17 | QSEE_1/DEVCFG_1/RPM_1/CDT_1 | 冗余备份 | |
| 18 | rootfs | 36MB | 系统 |
| 19 | rootfs_1 | 36MB | 双系统备份 |
| 20 | overlay | 36.6MB | |
| 21 | cfg_bak | 512KB | |
| 22-25 | kernel/ubi_rootfs/rootfs_data/data | UBI卷 | |

## 大分区布局（新 MIBIB）

| 分区 | 起始块 | 大小 |
|------|--------|------|
| 0:SBL1 | 0 | 1.5MB |
| 0:MIBIB | 12 | 1MB |
| 0:QSEE | 20 | 3.5MB |
| 0:DEVCFG/0:RPM/0:CDT/APPSBLENV | 48 | 各512KB |
| 0:APPSBL | 64 | 1.5MB |
| 0:ART/bdata/crash/crash_syslog | 76 | 各512KB |
| **rootfs** | **92** | **112MB** |

块大小 = 128KB。rootfs 从 36MB → 112MB，去掉冗余分区和双系统备份。

## MTD 写入注意事项

- 分区名含冒号（如 `0:MIBIB`），直接写会被 shell 解析
- 推荐用设备路径：`mtd write file /dev/mtd1`
- 或者加引号：`mtd write file "0:MIBIB"`
- MIBIB (mtd1) 在系统内被锁定，只能从 uboot 层写入
