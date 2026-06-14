#!/usr/bin/env python3
# breed_enter.py — 通过网络中断让 Newifi D2 进入 breed 恢复模式
#
# 协议: PC 广播 "BREED:ABORT" → 255.255.255.255:37541
#       收到 "BREED:ABORTED" (14 字节) 即成功
#
# 前置: 用户必须把 PC IP 设为 192.168.1.x/24
#       路由器已断电待上电 (breed 启动后只在很短时间内监听 37541,
#       用户需在 PC 命令发出后再插电)
#
# 多网卡: 默认绑定 0.0.0.0, 广播从所有接口发出, 响应从路由器所在接口回
#       --iface <name>  仅从指定接口收发 (Linux 走 SO_BINDTODEVICE)
#       --bind-ip <ip>  显式绑本机 IP (跨平台, 等价于绑定该 IP 所在接口)
#
# 输出: stdout = 单个 JSON (ok/ok:false + reason + recoverable)
#       stderr = 进度日志 (--debug 时)
#       exit  = 0 成功 / 1 通用 / 3 网络

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone

STEP_NAME = "breed_enter"
DEFAULT_TIMEOUT = 180
BROADCAST_INTERVAL = 0.05
ABORT_PAYLOAD = b"BREED:ABORT"
ABORTED_PAYLOAD = b"BREED:ABORTED"
BREED_PORT = 37541
LISTEN_PORT = 37540
BREED_WEB = "http://192.168.1.1"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）


def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str, recoverable: bool, data: dict) -> None:
    print(json.dumps({
        "ok": False, "step": STEP_NAME, "error": error,
        "reason": reason, "recoverable": recoverable, "data": data,
    }, ensure_ascii=False))


def _get_iface_ip(iface: str) -> str:
    """用 `ip` 命令取接口的第一个 IPv4 地址 (Linux/macOS).

    Windows 暂未支持, 报错让用户改用 --bind-ip."""
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


def breed_enter(timeout: int, open_browser: bool,
                iface: str = "", bind_ip: str = "") -> tuple[dict, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # 解析绑定的本地端点
    bind_addr = "0.0.0.0"
    if iface:
        # Linux 上 SO_BINDTODEVICE 真绑定接口, 不依赖 IP
        if hasattr(socket, "SO_BINDTODEVICE"):
            try:
                sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                    iface.encode() + b"\x00",
                )
                log(f"SO_BINDTODEVICE: {iface}")
            except (OSError, PermissionError) as e:
                log(f"SO_BINDTODEVICE 失败 ({e}), 改用 IP 绑定")
                bind_addr = _get_iface_ip(iface)
        else:
            bind_addr = _get_iface_ip(iface)
    elif bind_ip:
        bind_addr = bind_ip

    sock.bind((bind_addr, LISTEN_PORT))
    sock.setblocking(False)
    log(f"绑定 {bind_addr}:{LISTEN_PORT}")

    start = time.time()
    attempts = 0
    deadline = start + timeout
    log(f"监听 :{LISTEN_PORT}, 广播 → 255.255.255.255:{BREED_PORT}, timeout={timeout}s")

    try:
        while True:
            # 批量发送多个广播包，提高命中率
            for _ in range(5):
                try:
                    sock.sendto(ABORT_PAYLOAD, ("255.255.255.255", BREED_PORT))
                    attempts += 1
                except BlockingIOError:
                    pass

            # 检查是否有响应
            try:
                data, addr = sock.recvfrom(64)
                if data.strip() == ABORTED_PAYLOAD:
                    elapsed = round(time.time() - start, 2)
                    log(f"收到 BREED:ABORTED from {addr[0]}:{addr[1]}")
                    if open_browser:
                        try:
                            webbrowser.open(BREED_WEB)
                        except Exception as e:
                            log(f"无法打开浏览器: {e}", level="WARN")
                    return ({
                        "router_ip": BREED_WEB.replace("http://", ""),
                        "attempts": attempts,
                        "elapsed_sec": elapsed,
                    }, 0)
            except BlockingIOError:
                pass

            if time.time() >= deadline:
                elapsed = round(time.time() - start, 2)
                return ({
                    "attempts": attempts,
                    "elapsed_sec": elapsed,
                }, 3)

            time.sleep(BROADCAST_INTERVAL)
    finally:
        sock.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="通过 BREED:ABORT 广播让 Newifi D2 进入 breed 恢复模式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 默认 30s 超时, 收到响应即返回\n"
            "  python3 breed_enter.py\n"
            "  # 自定义超时 + 收到后自动开浏览器\n"
            "  python3 breed_enter.py --timeout 60 --open-browser\n"
            "  # 查看参数 Schema (供 AI 解析)\n"
            "  python3 breed_enter.py --help-json\n"
        ),
    )
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"超时秒数 (默认: {DEFAULT_TIMEOUT} = 3min)")
    p.add_argument("--open-browser", action="store_true",
                   help="成功后自动打开浏览器到 breed Web UI")
    p.add_argument("--iface", default="",
                   help="绑定到指定网卡 (如 enp0s26u1u1), Linux 走 SO_BINDTODEVICE")
    p.add_argument("--bind-ip", default="",
                   help="绑定到指定本机 IP (跨平台, 等价于该 IP 所在接口)")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr")
    return p.parse_args()


def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "通过 BREED:ABORT 广播让 Newifi D2 进入 breed 恢复模式",
        "args": [
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "超时秒数 (默认 180 = 3min)"},
            {"name": "--open-browser", "type": "flag", "default": False,
             "required": False, "description": "成功后自动打开浏览器"},
            {"name": "--iface", "type": "string", "default": "",
             "required": False, "description": "绑定网卡 (Linux 走 SO_BINDTODEVICE)"},
            {"name": "--bind-ip", "type": "string", "default": "",
             "required": False, "description": "绑定本机 IP (跨平台)"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 breed_enter.py",
            "python3 breed_enter.py --timeout 60 --open-browser",
            "python3 breed_enter.py --iface enp0s26u1u1",
            "python3 breed_enter.py --bind-ip 192.168.1.5",
        ],
        "stdin_contract": {"expects": "无", "produces": "含 router_ip 的成功 JSON"},
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0

    args = parse_args()
    DEBUG = args.debug

    started = time.time()
    data, code = breed_enter(args.timeout, args.open_browser,
                             args.iface, args.bind_ip)
    data["duration_ms"] = int((time.time() - started) * 1000)

    if code == 0:
        emit_ok(data)
        return 0
    emit_err(f"{args.timeout}s 内未收到 BREED:ABORTED, "
             "检查: 路由器是否已通电 / 本机 IP 是否在 192.168.1.x/24",
             "breed_not_responding", True, data)
    return 1


if __name__ == "__main__":
    sys.exit(main())
