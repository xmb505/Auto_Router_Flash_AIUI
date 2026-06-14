#!/usr/bin/env python3
# 3.ssh_enable.py — Newifi/Lecoo 步骤 3：通过 ubus API 开启 SSH
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 协议: ubus JSON-RPC → xapi.basic.open_dropbear
# 前置: 已有 ubus_rpc_session（通过 2.login_get_sid.py --pwd 获取）
# 后置: 路由器 dropbear 已启动（端口 22 可达）
#       可 SSH 登录：root / 管理密码
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_TIMEOUT = 10
STEP_NAME = "ssh_enable"
DEBUG = False


def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "unknown",
             recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def ubus_call(ip: str, sid: str, payload: dict, timeout: int) -> dict:
    url = f"http://{ip}/ubus"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"/ubus HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}") from e


def check_ssh_port(ip: str, port: int = 22, timeout: float = 3) -> bool:
    """快速检测 SSH 端口是否开放。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False


def ssh_enable(ip: str, sid: str, timeout: int) -> dict:
    """调用 xapi.basic.open_dropbear 开启 SSH。"""
    log("检查当前 SSH 状态...")
    before = check_ssh_port(ip)
    log(f"SSH 端口 22 之前: {'开放' if before else '关闭'}")

    log("调用 xapi.basic.open_dropbear...")
    resp = ubus_call(ip, sid, {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [sid, "xapi.basic", "open_dropbear", {}],
    }, timeout)

    result = resp.get("result")
    if not isinstance(result, list) or len(result) < 1:
        err = resp.get("error", {})
        code = err.get("code", -1)
        msg = err.get("message", str(resp)[:100])
        raise RuntimeError(f"open_dropbear 失败: {msg} (code={code})")

    rcode = result[0]
    if rcode != 0:
        raise RuntimeError(f"open_dropbear 失败: code={rcode}")

    log("等待 SSH 端口开放...")
    import time
    wait = 0
    while wait < 10:
        if check_ssh_port(ip):
            log(f"SSH 端口已开放（约 {wait}s）")
            break
        time.sleep(0.5)
        wait += 0.5
    else:
        log("SSH 端口未在 10s 内开放，可能仍在启动中")

    after = check_ssh_port(ip)
    return {
        "ip": ip,
        "ssh_port": 22,
        "ssh_enabled": after,
        "was_already_open": before,
        "username": "root",
        "password_hint": "管理密码（同 Web 登录密码）",
    }


def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="通过 ubus API 开启 Newifi/Lecoo 路由器 SSH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 3.ssh_enable.py --sid <ubus_rpc_session>\n"
            "  python3 3.ssh_enable.py --sid xxx --debug\n\n"
            "  完整 pipeline:\n"
            "  python3 2.login_get_sid.py --pwd 12345678 | \\\n"
            "    python3 -c 'import sys,json;print(json.load(sys.stdin)[\"data\"][\"sid\"])' | \\\n"
            "    xargs python3 3.ssh_enable.py --sid\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--sid", required=True,
                   help="ubus_rpc_session（32 位 hex）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "通过 ubus API（xapi.basic.open_dropbear）开启 Newifi/Lecoo 路由器 SSH",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--sid", "type": "string", "default": None,
             "required": True,
             "description": "ubus_rpc_session（32 位 hex）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False,
             "description": f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 3.ssh_enable.py --sid <ubus_rpc_session>",
            "python3 3.ssh_enable.py --sid a71f7f6a7b2352f7614d6a935baf11af",
        ],
        "stdin_contract": {
            "expects": "无（sid 从 --sid 参数传入）",
            "produces": "含 ssh_enabled=true 的成功 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json_schema()
        return 0

    args = build_argparse().parse_args()
    DEBUG = args.debug

    try:
        data = ssh_enable(args.ip, args.sid, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        if "连接失败" in msg:
            emit_err(msg, reason="network_unreachable", recoverable=True)
            return 3
        if "Access denied" in msg or "code=-32002" in msg:
            emit_err(msg, reason="sid_expired", recoverable=True)
            return 4
        emit_err(msg, recoverable=True)
        return 1
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), recoverable=True)
        return 1

    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
