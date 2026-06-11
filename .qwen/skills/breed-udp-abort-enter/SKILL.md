---
name: breed-udp-abort-enter
description: 通过 UDP 广播 BREED:ABORT 中断路由器启动进入 breed 恢复模式（适用于 Newifi D2 等支持该协议的 MT7621 路由器）
source: auto-skill
extracted_at: '2026-06-10T18:00:00.000Z'
---

# 协议级中断进入 breed 恢复模式

## 适用场景

路由器支持 **breed bootloader**（如 Newifi D2、Newifi 3、联想 Y1 等 MT7621 设备），且**官方固件 / OpenWrt 都引导失败**时，需要不依赖物理 reset 按钮、不拆机的"网络方式"进入 breed Web 恢复。

**触发条件**（三者全满足）：
- 路由器已**断电待上电**（或已上电但引导卡住）
- PC 与路由器**直连**（同 192.168.1.0/24 子网）
- 用户已把 PC IP 设为 `192.168.1.x/24`

## 协议层细节

| 字段 | 值 |
|------|-----|
| 出方向 | UDP 广播 `255.255.255.255:37541` |
| 出载荷 | `BREED:ABORT` (12 字节，固定字符串) |
| 入方向 | UDP `<router_ip>:37540` |
| 入载荷 | `BREED:ABORTED` (14 字节，确认中断成功) |
| 时间窗 | 路由器上电后 breed 启动后约 1~5 秒（窗口短，必须抢） |

**核心机制**：breed 启动时短暂监听 37541 端口，收到 `BREED:ABORT` 后**放弃引导 firmware**、停在 Web 恢复模式。回送 `BREED:ABORTED` 是状态确认（过去时后缀 `ED` 表示"已做"）。

## 多网卡场景

默认 `bind(("0.0.0.0", 37540))` + 广播 `255.255.255.255:37541`，在多网卡机器上会从**所有接口**发出广播，并从任意接口接收响应。多网卡场景下用户需指定出口：

| 参数 | 行为 | 平台 |
|------|------|------|
| `--iface <name>` | Linux 走 `SO_BINDTODEVICE` 真绑定接口；其他平台降级用 `ip` 命令取 IP | 全平台 |
| `--bind-ip <ip>` | `bind((ip, 37540))`，等价于绑该 IP 所在接口 | 全平台 |
| (不传) | 绑 `0.0.0.0`，广播从所有接口发 | 全平台 |

详见 `udp-multi-nic-bind` 技能。

## 不依赖物理按钮的好处

| 传统方式 | 本协议 |
|---------|-------|
| 按住 reset → 插电 → 等 LED → 松手 | 路由器断电 → PC 跑命令 → 用户插电 |
| 时序错了就白搭 | 时序容错（500ms 重发） |
| 看不到路由器 | PC 在同一子网即可 |

## Python 实现范式（直接套用 breed_enter.py）

### 关键代码骨架（支持多网卡绑定）

```python
import platform
import socket
import subprocess
import time

# 协议常量
ABORT_PAYLOAD = b"BREED:ABORT"
ABORTED_PAYLOAD = b"BREED:ABORTED"
BREED_PORT = 37541      # 路由器 breed 监听
LISTEN_PORT = 37540     # PC 接收响应的端口
BROADCAST_ADDR = "255.255.255.255"
BREED_WEB = "http://192.168.1.1"
DEFAULT_TIMEOUT = 180   # 3 min, 给用户留出插电时间


def _get_iface_ip(iface: str) -> str:
    """用 `ip` 命令取接口的第一个 IPv4 (Linux/macOS)"""
    if platform.system() == "Windows":
        raise RuntimeError("Windows 不支持 --iface, 改用 --bind-ip")
    out = subprocess.run(
        ["ip", "-o", "-4", "addr", "show", "dev", iface],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"interface 未找到或无 IPv4: {iface}")
    for line in out.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    raise RuntimeError(f"no IPv4 on interface: {iface}")


def breed_enter(timeout: int, iface: str = "", bind_ip: str = ""):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # 多网卡绑定解析
    bind_addr = "0.0.0.0"
    if iface:
        if hasattr(socket, "SO_BINDTODEVICE"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                iface.encode() + b"\x00")
            except (OSError, PermissionError):
                bind_addr = _get_iface_ip(iface)  # 降级
        else:
            bind_addr = _get_iface_ip(iface)
    elif bind_ip:
        bind_addr = bind_ip

    sock.bind((bind_addr, LISTEN_PORT))
    sock.setblocking(False)  # 关键：非阻塞

    deadline = time.time() + timeout
    attempts = 0
    try:
        while True:
            attempts += 1
            sock.sendto(ABORT_PAYLOAD, (BROADCAST_ADDR, BREED_PORT))

            try:
                data, addr = sock.recvfrom(64)
                if ABORTED_PAYLOAD in data:
                    return {"ok": True, "router_ip": BREED_WEB,
                            "attempts": attempts,
                            "elapsed_sec": round(time.time() - (deadline - timeout), 2)}

            except BlockingIOError:
                pass

            if time.time() >= deadline:
                return {"ok": False, "attempts": attempts,
                        "elapsed_sec": timeout}

            time.sleep(0.5)
    finally:
        sock.close()
```

### 五个不能省的关键点

1. **`SO_REUSEADDR`** — 防止前一次运行残留 TIME_WAIT 占着 37540，重启脚本就 bind 失败
2. **`setblocking(False)`** — 否则 `recv_from` 会阻塞超过 500ms 周期，导致下一帧 broadcast 错过 breed 窗口
3. **`try/finally sock.close()`** — Ctrl-C 中断时不能泄漏 socket，否则下次跑会 port already in use
4. **多网卡时必须 `--iface` 或 `--bind-ip`** — 默认 `0.0.0.0` 广播从所有接口发，多网卡机器上浪费带宽 + 串扰
5. **`SO_BINDTODEVICE` 失败时降级到 IP 绑定** — 需要 `CAP_NET_RAW` 或 root；非 root 用户下用 `ip` 命令取 IP 等效

## JSON 输出契约（按项目规范）

**成功**：
```json
{
  "ok": true,
  "step": "breed_enter",
  "data": {
    "router_ip": "192.168.1.1",
    "attempts": 7,
    "elapsed_sec": 3.2,
    "duration_ms": 3210
  }
}
```

**失败（最常见，超时）**：
```json
{
  "ok": false,
  "step": "breed_enter",
  "error": "180s 内未收到 BREED:ABORTED, 检查: 路由器是否已通电 / 本机 IP 是否在 192.168.1.x/24",
  "reason": "breed_not_responding",
  "recoverable": true,
  "data": {"attempts": 360, "elapsed_sec": 180.0, "duration_ms": 180050}
}
```

`reason="breed_not_responding"` 是 AI 在 `troubleshooting.md` 中按 `[reason]` 索引的键。`recoverable=true` 表示可以重试（用户重插电源后再次跑）。

## CLI 参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--timeout` | int | 180 (3min) | 等待 `BREED:ABORTED` 的最长时间 |
| `--open-browser` | flag | false | 成功后自动 `webbrowser.open("http://192.168.1.1")` |
| `--iface` | string | "" | 绑指定网卡（Linux 走 `SO_BINDTODEVICE`） |
| `--bind-ip` | string | "" | 绑指定本机 IP（跨平台） |
| `--debug` | flag | false | 打印 `[INFO] ...` 进度到 stderr |
| `--help-json` | flag | — | 输出参数 JSON Schema（供 AI 自动构造命令） |

3 分钟默认超时是**给用户留出"插电源"的反应时间**——脚本启动时用户可能还没来得及给路由器上电。如果路由器已经上电了，响应通常在 1~5 秒内到。

## 常见问题与排错

| 现象 | 原因 | 解决 |
|------|------|------|
| 一直 timeout | 路由器没上电 / 时序错 | 用户**先**跑脚本再**插电源**，让 PC 先开始广播 |
| 一次都没收到 | PC 不在 192.168.1.0/24 | `ip addr` 确认本机 IP |
| 收到非 BREED:ABORTED | 网络上其他设备的 UDP 噪音 | `if ABORTED_PAYLOAD in data` 已经过滤 |
| 第二次跑 bind 失败 | 旧 socket TIME_WAIT | `SO_REUSEADDR` 已处理；仍失败就 `pkill -f breed_enter` |

## 与其他技能的搭配

- **`step-script-default-silent-debug`** —— 本脚本遵循同样的 `--debug` 模式
- **`unix-philosophy-router-refactor`** —— 步骤脚本是单文件、不靠 import 复用
- **`udp-multi-nic-bind`** —— 多网卡场景下 `--iface` / `--bind-ip` 的实现细节
- **机型 doc** —— `newifid2/doc/flash-pipeline.md` 写明这是流水线第一步

## 适用范围之外

- **不适用于 AX3600 / AX6**（IPQ8071A 走小米 `set_config_iotdev` 注入路径，不是 breed 协议）
- **不适用于纯 OpenWrt 状态**（如果路由器已正常运行 OpenWrt，直接 SSH sysupgrade 即可，不需要进 breed）
- **不适用于 uboot 而不是 breed 的设备**（协议字节不同，14 字节响应也不对）

## 复用到其他 bootloader

如果未来有其他 bootloader 实现类似"启动期监听特定端口、接受 abort 命令"的协议，可以按本模式重写：
1. 替换 `ABORT_PAYLOAD` / `ABORTED_PAYLOAD` / 端口号
2. 保留 UDP 广播 + 非阻塞 recv + deadline loop 骨架
3. 改 `reason` 字符串
4. 更新 `troubleshooting.md` 对应条目

## 范本代码位置

`src/project/newifid2/breed_enter.py` —— 完整范本，含 `--help-json` / `--open-browser` / `--debug`。

## 验收清单

写完一个 breed_enter 风格的脚本后：
- [ ] 协议载荷/端口是常量（不写死在循环里）
- [ ] `SO_BROADCAST` + `SO_REUSEADDR` 都有
- [ ] `setblocking(False)`
- [ ] `try/finally` 关 socket
- [ ] 周期可调但默认 500ms
- [ ] 超时 exit 1，成功 exit 0
- [ ] JSON 包含 `reason`（失败时）和 `recoverable`
- [ ] `troubleshooting.md` 有对应 `[reason]` 条目
