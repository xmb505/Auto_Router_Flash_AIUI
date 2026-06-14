---
name: model-orchestrator-pattern
description: 为路由器刷机项目创建 all_official_2_openwrt.py 编排器的通用模式——INI 配置、ping/init_info 检测、降级分支、stok 传播、等待重启、分区切换 (project)
source: auto-skill
extracted_at: '2026-06-14T06:12:34.977Z'
---

# 机型编排器模式 (all_official_2_openwrt.py)

基于 newifid2 和 AX5 的两轮实机验证，提取出为每个新机型编写编排器的标准模式。

## 适用场景

有一个已经步骤脚本化（`N.step.py` + 工具 `.sh`）的机型，需要写一个端到端编排器把步骤串起来。

## 文件约定

```
src/project/<机型>/
├── all_official_2_openwrt.py     # 编排器（主入口）
├── all_official_2_openwrt.ini    # INI 配置（固件路径）
└── ...（其他步骤脚本/工具不变）
```

## INI 配置文件

```ini
[firmware]
ubi_file = files/<固件名>.ubi
downgrade_file = files/<降级固件>.bin      ; 可选，不填跳过降级
```

INI 是 CLI 和代码之间的「配置层」：固件路径放 INI，密码/IP 等运行时参数走 CLI。INI 用 `configparser` 读，key 用 `section.key` 扁平化。

## 编排器骨架

### 核心模块

| 模块 | 职责 | 参考实现 |
|------|------|---------|
| `ping_host/wait_ping_down/wait_ping_up` | 路由器上下线检测 | `subprocess.run(["ping", "-c", "1", ...])` |
| `wait_port_open` | SSH 端口探测 | `socket.create_connection((ip, port), timeout=3)` |
| `fetch_init_info` | 读 init_info 获知状态 | `GET /cgi-bin/luci/api/xqsystem/init_info` |
| `run_script` | 执行子脚本、解析 JSON、校验 ok | 同 newifid2 模式 |
| `run_shell_script` | 执行 .sh 脚本、解析 JSON | 调用 `miwifi_ssh.sh` 等 |
| `read_config` | 读 INI 文件 | `configparser.ConfigParser` |
| `needs_downgrade` | 版本检查 | 匹配特定版本（如 `"1.0.26"`），不是 1.0.26 就需降级 |

### inited=1 处理（经验修正）

不要立即报错，先试默认密码：

```python
if inited == 1:
    try:
        login_data = run_script(["2.login_get_stok.py", "--pwd", pwd], ...)
        stok = login_data.get("stok", "")
        if stok:
            _skip_init = True  # 跳过 init，直接往后走
    except:
        raise RuntimeError("inited=1, 默认密码登录失败，请物理 Reset")
```

### SSH 启用后等待 + 重试

`set_config_iotdev`/`start_binding` 注入成功 ≠ SSH 立即可用。dropbear 需数秒启动，有时甚至需要重试注入：

```python
SSH_RETRY_MAX = 3
SSH_RETRY_WAIT = 15

for attempt in range(1, SSH_RETRY_MAX + 1):
    run_script(["3.enable_ssh.py", "--stok", stok], ...)
    time.sleep(SSH_RETRY_WAIT)
    if wait_port_open(ip, 22, 60):
        break
    log(f"SSH 未就绪，重试 ({attempt}/{SSH_RETRY_MAX})")
```

### OpenWrt 上线等待 + overlay 重试

Ping 通 ≠ SSH 就绪。先等 SSH 再跑 overlay：

```python
openwrt_online = False
if wait_ping_up("192.168.1.1", 120):
    if wait_port_open("192.168.1.1", 22, 60):
        openwrt_online = True

if overlay and openwrt_online:
    for attempt in range(1, 4):
        try:
            run_script(["7.custom_openwrt.py", "--file", overlay], ...)
            break
        except RuntimeError:
            if attempt < 3:
                time.sleep(10)
```

### `--step` 分水岭参数

支持跳过 stock 阶段直接进 initramfs 模式（主要用于 AX3000T）：

```python
p.add_argument("--step", type=int, default=1, choices=[1, 5],
               help="起始步骤（1=从头, 5=initramfs 模式）")

if step >= 5:
    log("initramfs 模式，跳过 stock")
else:
    # 完整的 stock 流程（ping → init → login → SSH → flash_uboot）
    ...

# 阶段 5+ (sysupgrade + overlay) 两种模式都走
```

### `run_shell_script` 兼容 flat JSON

Shell 脚本（如 `miwifi_ssh.sh`、`set_uboot_env.sh`）返回的 JSON 格式不统一：
- 数组：`[{ok:true, cmd:..., stdout:...}]`
- 扁平对象：`{ok:true, ip:..., flags:...}`（无 `data` 字段）

```python
if isinstance(data, list):
    for item in data:
        if not item.get("ok"):
            raise RuntimeError(...)
    return data[0]
if not data.get("ok"):
    raise RuntimeError(...)
return data.get("data", {k: v for k, v in data.items() if k != "ok"})  # 扁平兼容
```

### 降级后等待：sleep + 轮询 HTTP

不能用固定 sleep——路由器先 ping 通但 HTTP 服务还在重启。
先 `wait_ping_up`，再 `wait_http_ready`（轮询 init_info 含 inited 字段）。

### FIP uboot 刷写后 sleep 60s

AX3000T 等 FIP 机型，`4.flash_uboot.py` 重启后 uboot 需 ~60s 通过 TFTP 拉 initramfs。
用 `time.sleep(60)` 等 initramfs 就绪再跑后续步骤。

### 执行流程

```
Phase 0: 检测
  ping 192.168.31.1 → 确认在线
  GET init_info → 提取 model, hardware, romversion, inited
  验证 hardware 是否匹配本机型
  如果 inited=1 → 报错要求物理 Reset（不知道密码）
  steps_done.append("factory_ok")

Phase 1: 出厂初始化
  1.official_init.py --admin-pwd <pwd>
  → 返回 stok（但改密后失效，丢弃）
  steps_done.append("1.official_init")

Phase 2: 登录拿 stok
  2.login_get_stok.py --pwd <pwd>
  → 返回 stok（存为变量，后续传播）
  steps_done.append("2.login_get_stok")

Phase 3: 降级（可选）
  if downgrade_file and needs_downgrade(romversion):
    <downgrade_command> --stok <stok> --file <downgrade_file>
    → will_reboot
    wait_ping_down(30s)
    wait_ping_up(120s)
    wait_http_ready()  ← 轮询 init_info 直到 HTTP 返回有效 JSON
    → 重新 init + login（降级清 NVRAM）
    steps_done.append("3.downgrade")

Phase 4: 启用 SSH
  <enable_ssh_command> --stok <stok>
  time.sleep(10)      ← set_config_iotdev 注入后 dropbear 启动慢
  如果 SSH 没开: 重试 enable_ssh 最多 3 次（AX3600 实测需要）
  wait_port_open(22, 90s)
  steps_done.append("4.enable_ssh")

Phase 5: 上传固件
  5.firmware_upload_on_miwifi.py --file <ubi_file>
  target = os.path.basename(data.get("target"))  ← .sh 返回 /tmp/xxx 需取 basename
  steps_done.append("5.firmware_upload")

Phase 6: 烧镜像
  6.miwifi_2_openwrt.py --file-name <basename>
  → 返回 target_mtd, part
  steps_done.append("6.miwifi_2_openwrt")

Phase 7: 切分区
  set_miwifi_uboot_partition.sh --ip <ip> --part <part>
  steps_done.append("set_miwifi_uboot_partition")

Phase 8: 重启
  miwifi_ssh.sh --cmd reboot
  steps_done.append("reboot")
  wait_ping_up(192.168.1.1, 120s)  ← 等 OpenWrt 上线（IP 从 stock 变 OpenWrt）

### 关键原则（来自实机测试教训）

1. **`--pwd` 默认 `12345678`，不是 `admin`**。因为 `1.official_init.py --admin-pwd <pwd>` 设的密码就是 12345678。工厂态密码永远和 `--admin-pwd` 一致。
2. **INI 管固件路径，CLI 管运行时参数**。`--firmware` 不需要 CLi 传，从 INI 读。
3. **`inited=1` 直接报错，不要尝试猜密码**。物理 Reset 是唯一已知路径。
4. **init 返回的 stok 改密后失效**，必须 `2.login_get_stok.py` 重新拿。
5. **等待重启用 ping**（down→up），不是 HTTP 探测。ping 更可靠地反映路由器状态。
6. **传播 stok 用变量，不写文件**。stok 是敏感令牌，只存在内存里。
7. **`run_shell_script` 必须处理 JSON 数组**。`miwifi_ssh.sh --cmd` 返回 `[{ok:..., cmd:...}]`，不是 `{ok:..., data:...}`。function 内部需检查 `isinstance(data, list)`。
8. **降级后等 HTTP 就绪用轮询，不用 `sleep`**。`wait_http_ready()` 每 1s 轮询 `init_info` 直到返回有效 JSON（含 `inited` 字段），最多等 120s。
9. **SSH 注入后 dropbear 不一定立即启动**。AX3600 实测 `3.enable_ssh` 返回成功但 SSH 端口 90s 都没开。方案：先 `sleep(10)`，再 `wait_port_open`，如果超时就重试 `enable_ssh`（最多 3 次）。
10. **AX3000T 用 `--step 5` 分叉**。pipelines 类型不同（FIP+TFTP vs ubiformat）时，用 `if step >= 5: skip stock` 做顶部 fork，不把条件散落在各阶段里。
11. **`5.sysupgrade_openwrt.py` 的 `wait_openwrt_boot` 需要两段式**：先等 SSH 断连（sysupgrade 触发重启），再等 SSH 上线（新系统）。单段式会卡在 initramfs SSH 还开着的时候。
12. **`miwifi_ssh.sh` 的 `json_str` 必须转义 `\r`**。SSH auth 失败时 `sshpass` 输出含 `\r` 字符，不作转义会破坏 JSON 格式导致 AI 解析失败。

### 错误处理

- 所有子脚本失败均抛 `RuntimeError`，`main()` 里 catch
- `emit_err` 输出 `failed_step`（失败的步骤名）和 `steps_done`（已成功的步骤列表）
- AI 通过 `steps_done` 知道从哪里恢复

### 必须的 import

```python
import argparse
import configparser
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
```

### 派生新机型的步骤

1. 复制 `all_official_2_openwrt.ini`，改 `ubi_file` 路径
2. 复制 `all_official_2_openwrt.py`，改：
   - 机型名、header 注释
   - `STEP_NAME`（可选）
   - 各步骤脚本的参数名（不同机型可能有差异）
   - 硬件验证的硬件名
   - 降级版本前缀（如果不同）
3. 验证步骤脚本 `--help` 参数名与实际一致
4. `python3 all_official_2_openwrt.py --debug` 实测

## 参考实现

- `src/project/newifid2/all_official_2_openwrt.py` — 原始模式（子编排器模式）
- `src/project/ax5/all_official_2_openwrt.py` — 直接调步骤脚本模式（本模式的标准参考）
