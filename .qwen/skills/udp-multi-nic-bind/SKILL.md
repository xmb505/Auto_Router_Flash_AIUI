---
name: udp-multi-nic-bind
description: UDP socket 在多网卡机器上绑定到指定接口的跨平台模式（--iface / --bind-ip 双参数；Linux 走 SO_BINDTODEVICE，其他平台走 ip 命令取 IP）
source: auto-skill
extracted_at: '2026-06-10T18:40:00.000Z'
---

# UDP socket 多网卡绑定模式

## 适用场景

写需要发广播 / 多播 / 单播 UDP 的脚本（如 breed abort、DHCP discover、TFTP 客户端、自定义发现协议），且**用户机器有多块网卡**时使用。

**问题**：默认 `bind(("0.0.0.0", port))` + 广播 `255.255.255.255`，内核会从**所有**接口发出广播，浪费带宽；多个子网各有路由器时还会串扰。

**解决**：让用户显式指定出口。

## 双参数设计

| 参数 | 作用 | 平台 |
|------|------|------|
| `--iface <name>` | 按接口名绑定 | Linux 用 `SO_BINDTODEVICE`，其他平台降级 |
| `--bind-ip <ip>` | 按本机 IP 绑定（等价于该 IP 所在接口） | 全平台 |
| (不传) | 默认 `0.0.0.0`，所有接口 | 全平台 |

**优先级**：`--iface` > `--bind-ip` > 默认。

## 完整实现模式

```python
import platform
import socket
import subprocess


def _get_iface_ip(iface: str) -> str:
    """取接口的第一个 IPv4 地址 (Linux/macOS). Windows 报错让用户改 --bind-ip."""
    if platform.system() == "Windows":
        raise RuntimeError("Windows 不支持 --iface, 请改用 --bind-ip")
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


def bind_socket(sock: socket.socket, iface: str = "", bind_ip: str = ""):
    """应用绑定策略. 必须在 sock.bind() 之前调用."""
    bind_addr = "0.0.0.0"
    if iface:
        if hasattr(socket, "SO_BINDTODEVICE"):
            try:
                sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                    iface.encode() + b"\x00",
                )
                # SO_BINDTODEVICE 成功时, bind_addr 仍可保持 0.0.0.0
                # 因为内核已经知道从哪个接口走
            except (OSError, PermissionError):
                # 非 root / 无 CAP_NET_RAW 时降级
                bind_addr = _get_iface_ip(iface)
        else:
            # 非 Linux 平台
            bind_addr = _get_iface_ip(iface)
    elif bind_ip:
        bind_addr = bind_ip
    sock.bind((bind_addr, PORT))
    return bind_addr
```

## 关键决策的理由

| 决策 | 原因 |
|------|------|
| `SO_BINDTODEVICE` 优先 | 真绑定接口，不依赖 IP 存在/不变；接口无 IP 也能用 |
| 失败降级到 IP 绑定 | `SO_BINDTODEVICE` 需要 `CAP_NET_RAW`（普通 root 不一定有） |
| `ip` 命令而非 `fcntl(SIOCGIFADDR)` | 跨平台（Linux/macOS 都有 `ip`）；`fcntl` Linux-only |
| Windows 直接报错 | `if_nameindex()` 拿到 index 但 `SO_BINDTODEVICE` 不存在；让用户改用 `--bind-ip` |
| 不支持枚举接口 | 用户知道自己要绑哪个，不需要脚本替他猜 |
| 失败时回退到 `0.0.0.0` | `RuntimeError` 让上层 emit_err 报 `iface_unavailable` reason |

## argparse 标准定义

```python
p.add_argument("--iface", default="",
               help="绑定到指定网卡 (如 enp0s26u1u1), Linux 走 SO_BINDTODEVICE")
p.add_argument("--bind-ip", default="",
               help="绑定到指定本机 IP (跨平台, 等价于该 IP 所在接口)")
```

## --help-json schema 同步

```json
{
  "name": "--iface", "type": "string", "default": "",
  "required": false, "description": "绑定网卡 (Linux 走 SO_BINDTODEVICE)"
},
{
  "name": "--bind-ip", "type": "string", "default": "",
  "required": false, "description": "绑定本机 IP (跨平台)"
}
```

## 失败 reason 分类

| 触发 | reason | recoverable | 错误示例 |
|------|--------|-------------|----------|
| `--iface` 不存在的接口名 | `iface_not_found` | true | `interface 未找到或无 IPv4: xxx` |
| Windows 用了 `--iface` | `iface_unsupported_os` | true | `Windows 不支持 --iface, 改用 --bind-ip` |
| `SO_BINDTODEVICE` 失败 + 找不到 IP | `iface_no_ipv4` | true | `no IPv4 on interface: xxx` |
| `--bind-ip` 不在本机 | `bind_ip_not_local` | true | `Cannot assign requested address` |

## 与 broadcast 配合的注意点

```python
# 1. SO_BROADCAST 必须显式 enable (即使 SO_BINDTODEVICE 后)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

# 2. SO_REUSEADDR 防 TIME_WAIT
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# 3. SO_BINDTODEVICE 在 bind() 之前调用（已在 bind_socket 内处理）
```

## 已知坑

1. **`SO_BINDTODEVICE` 的 ifname 必须以 `\x00` 结尾** — Python 字符串不带 NUL，需要手动 `encode() + b"\x00"`
2. **`ip -o` 输出格式**：`2: enp0s26u1u1    inet 192.168.1.2/24 ...` — `inet` 索引找 IP，不是位置
3. **接口名不要带 `:` 等特殊字符** — systemd 命名（`enp0s26u1u1u1`）可能有，shell 转义要小心
4. **`SO_BINDTODEVICE` + VPN** — wireguard/tun 接口可能没 IP 但有路由，需特殊处理
5. **macOS 无 `SO_BINDTODEVICE`** — 即使内核支持 BPF，Python socket 模块不暴露；用 IP 绑定即可

## 与现有技能的关联

- **`breed-udp-abort-enter`** — `breed_enter.py` 是本模式的第一个实战应用
- 未来脚本（TFTP 客户端、mDNS 探测、链路层发现）按需复用 `bind_socket()` 即可

## 验收清单

新增/修改任何带 `--iface` / `--bind-ip` 的脚本时：
- [ ] `_get_iface_ip()` 实现了 IP 解析
- [ ] `SO_BINDTODEVICE` 调用带 NUL 终止符
- [ ] 非 Linux 平台降级到 IP 绑定而非崩溃
- [ ] `bind()` 之后 `setblocking()` 等其他 setsockopt 仍正常
- [ ] `--help` 和 `--help-json` 同步更新
- [ ] `bind_ip_not_local` / `iface_not_found` 失败 reason 在 `troubleshooting.md` 有对应条目
