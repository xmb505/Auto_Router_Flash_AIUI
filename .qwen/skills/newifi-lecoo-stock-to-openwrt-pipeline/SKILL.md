---
name: newifi-lecoo-stock-to-openwrt-pipeline
description: Newifi D2 / Lecoo 从联想官方固件（PandoraBox 衍生）全自动刷入 OpenWrt/ImmortalWrt 的完整流水线：ubus 登录 → 开 SSH → 内核模块注入 breed → breed 刷 initramfs → initramfs sysupgrade
source: auto-skill
extracted_at: '2026-06-13T13:15:04.448Z'
---

# Newifi/Lecoo Stock → OpenWrt 全自动流水线

## 适用机型

- Newifi D2（新路由3）— 官方版（`newifi-d2`）或联想 Lecoo 版（`newifi-d2l`）
- SoC: MediaTek MT7621A (MIPS)
- 固件: 联想 Lecoo 官方固件 / 新路由官方固件（内核 3.14.79，平台 `newifi-d2`/`newifi-d2l`）
- 默认 IP: `192.168.99.1`

## 与小米流水线的关键区别

| 维度 | 小米 (AX6/AX3600) | Newifi/Lecoo |
|------|-------------------|--------------|
| 认证 | stok（AES 密文 + URL 路径） | ubus_rpc_session（JSON-RPC 2.0 + POST body） |
| 开 SSH | iotdev/smartcontroller 漏洞注入 | **合法 API** `xapi.basic.open_dropbear` |
| 写 bootloader | ubiformat + mtd write | **内核模块方式** `insmod newifi-d2-jail-break.ko` |
| 最终刷机 | 直接走 stock upgrade API | **两段式**：breed 刷 initramfs → sysupgrade |
| 原生 ssh | 不开放（需漏洞提权） | **有公共 API** 可开 |

## 流水线步骤

### 步骤 0：状态探测

```bash
# 检测路由器初始化状态（无需密码，无副作用）
python3 check_init.py --ip 192.168.99.1
# → is_inited=true  → 已有密码，直接走步骤 2
# → is_inited=false → 刚恢复出厂，先走步骤 1
```

### 步骤 1：初始化（仅恢复出厂后需要）

```bash
# 设置管理密码（默认密码为空或 admin）
python3 1.lecco_init.py --ip 192.168.99.1 --pwd 12345678
# → 返回 sid，但该 sid 不可用于后续操作！

# ⚠️ 关键陷阱：init 用旧密码登录，设置新密码后会话销毁
# 必须重新登录拿新鲜 sid：
python3 2.login_get_sid.py --ip 192.168.99.1 --pwd 12345678
```

### 步骤 2：登录获取 ubus_rpc_session

```bash
python3 2.login_get_sid.py --ip 192.168.99.1 --pwd 12345678
# → {"sid": "xxx...", "expires": 300}
```

**登录细节**（需逆向前端 JS）：
- 用户名**硬编码**为 `root`（不是 `admin`）
- 密码 **base64 编码**后传输
- 调 `session.xapi_login` 方法
- 返回 `ubus_rpc_session`（32 位 hex），有效期 300 秒
- 使用方式：作为 ubus 调用的 `params[0]` 传入

### 步骤 3：开启 SSH

```bash
python3 3.ssh_enable.py --ip 192.168.99.1 --sid <sid>
# → 调 xapi.basic.open_dropbear → SSH 22 端口秒开
```

### 步骤 4：注入 Breed Bootloader

```bash
python3 4.breed_inject.py --ip 192.168.99.1 --pwd 12345678 \
  --file files/newifi-d2-jail-break.ko
# 流程：SCP 上传 .ko → SSH insmod → breed 写入 Flash
# → SSH 断连 = breed 写入成功，路由器重启
```

**工作原理**：
- `.ko` 是内核模块，insmod 后自动将 breed 写入 `mtd0`（Bootloader 分区）
- 之后路由器重启，breed 作为新 bootloader 启动
- breed 能 chainload/引导原厂固件，所以路由器重启后仍可正常进入 stock 系统
- 在 breed 模式中按 Reset 上电可进入 breed Web 恢复模式

### 步骤 5：进入 Breed 模式

```bash
# 方式一：Reset 按钮上电（手动）
# 按住 Reset 孔 → 通电 → 等 5s → 松开 → breed 模式（192.168.1.1）

# 方式二：breed_enter.py（UDP 广播 ABORT）
python3 breed_enter.py --ip 192.168.1.1
# 需要先断电再上电，脚本在上电瞬间发 BREED:ABORT
```

### 步骤 6：Breed 刷入 Initramfs

```bash
# ⚠️ breed 不能直接刷 sysupgrade 固件！
# 必须两段式：先刷 initramfs，再从 initramfs shell 内 sysupgrade
python3 5.breed_flash_firmware.py \
  --file files/openwrt-25.12.4-ramips-mt7621-d-team_newifi-d2-initramfs-kernel.bin \
  --ip 192.168.1.1
# → 100% 进度（约 40s）→ 路由器自动重启
```

### 步骤 7：Sysupgrade 到最终固件

```bash
# 1. 等 Initramfs OpenWrt 启动（SSH 端口 22 可达，无密码）
# 2. SCP 上传 sysupgrade 固件
scp files/immortalwrt-*-squashfs-sysupgrade.bin root@192.168.1.1:/tmp/firmware.bin

# 3. 执行 sysupgrade（-n = 不保留配置，等同首次刷机）
ssh root@192.168.1.1 "sysupgrade -n /tmp/firmware.bin"
# → SSH 断连 = 刷写完成，路由器自动重启到新固件
```

## 完整的全自动流水线

```bash
# 一键全流程（以 stock 固件密码 12345678 为例）
cd src/project/newifid2

# 0) 检测状态
python3 check_init.py --debug

# 1) 初始化（如果需要）
python3 1.lecco_init.py --pwd 12345678

# 2) 登录拿 sid
SID=$(python3 2.login_get_sid.py --pwd 12345678 \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['sid'])")

# 3) 开 SSH
python3 3.ssh_enable.py --sid "$SID"

# 4) 注入 breed
python3 4.breed_inject.py --pwd 12345678 --debug

# → 手动切换至 breed 模式（Reset 上电）
# 5) breed 刷 initramfs
python3 5.breed_flash_firmware.py \
  --file files/openwrt-*-initramfs-kernel.bin --debug

# 6) 等 initramfs 起来后 sysupgrade
sshpass -p "" ssh -o StrictHostKeyChecking=no root@192.168.1.1 true
sshpass -p "" scp -O files/immortalwrt-*-squashfs-sysupgrade.bin \
  root@192.168.1.1:/tmp/firmware.bin
sshpass -p "" ssh root@192.168.1.1 "sysupgrade -n /tmp/firmware.bin"
```

## 脚本清单

| # | 脚本 | 功能 | 前置 | 执行阶段 |
|---|------|------|------|---------|
| — | `check_init.py` | 探测 guide_status（无需密码） | 路由 HTTP 可达 | Stock |
| 1 | `1.lecco_init.py` | 恢复出厂后初始化（设密码） | guide_status=0 | Stock |
| 2 | `2.login_get_sid.py` | 登录获取 ubus_rpc_session | 已初始化 + 密码 | Stock |
| 3 | `3.ssh_enable.py` | 开启 SSH（xapi.basic.open_dropbear） | sid | Stock |
| 4 | `4.breed_inject.py` | SCP 上传 .ko + insmod 写 breed | SSH 已开 + .ko | Stock |
| — | `breed_enter.py` | UDP 广播进入 breed 模式 | 断电待上电 | Boot |
| 5 | `5.breed_flash_firmware.py` | breed Web 刷 initramfs | breed 模式 | Breed |
| — | `openwrt_modern_standard_ssh.sh` | SSH 连 OpenWrt（旧辅助脚本） | OpenWrt | OpenWrt |

## 关键陷阱

### 1. init 返回的 sid 不可用

`1.lecco_init.py` 用出厂默认密码（空/admin）登录拿到 sid，再调 `set_login_passwd_base64` 设置新密码。设置后旧密码 session 被销毁，返回的 sid 已经失效。

**必须**：设置完密码后，再用 `2.login_get_sid.py --pwd <新密码>` 重新登录拿新 sid。

### 2. ubus_rpc_session 有效期 300s

sid 只有 5 分钟有效。超时后需要重新登录。每次 API 调用会刷新超时计时，但长耗时操作（如 breed 注入）前最好重新拿 sid。

### 3. Breed 严禁刷 sysupgrade

Breed Web 只接受裸 initramfs kernel 或编程器固件。sysupgrade 是 OpenWrt 专有格式（含 metadata 头/分区表），breed 不识别。**必须两段式**：breed 刷 initramfs → 进入 shell → sysupgrade。

### 4. 密码 base64 编码 + 用户名 root

登录时用户名是**前端 JS 硬编码的 `root`**，不是 `admin`。密码要先 base64 编码再传输。

### 5. SCP 需 -O 参数

Lecoo/Newifi 的 dropbear 只有旧 SCP 协议，没有 sftp-server。SCP 时需加 `-O` 参数（强制旧协议）。

## 来源

- 2026-06-13 全链路实机验证（Newifi D2 官方版 `newifi-d2` + Lecoo 版 `newifi-d2l`）
- 前端 JS 逆向获知 `root` 硬编码 + base64 密码编码
- `.ko` 文件 `newifi-d2-jail-break.ko`（2018-10-14，193KB）用于写入 breed
- Breed 版本 1.1 (r1237) 2018-10-14
