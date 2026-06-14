#!/usr/bin/env python3
# 2.login_get_sid.py — Newifi/Lecoo 步骤 2：登录并获取 ubus_rpc_session
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 协议: JSON-RPC 2.0 over HTTP POST /ubus
#       密码 base64 编码，用户名固定 root
# 前置: 路由器已初始化（已知管理密码）
# 后置: data.sid = ubus_rpc_session（32 位 hex token，有效期 300s）
#       可复用：sid 作为后续 ubus 调用的认证参数
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 2 参数 / 3 网络 / 4 认证 / 5 超时

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_TIMEOUT = 10
ANON_SID = "00000000000000000000000000000000"
STEP_NAME = "login_get_sid"
DEBUG = False


# ============ 日志 / 输出 ============

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


# ============ HTTP 工具 ============

def ubus_call(ip: str, payload: dict, timeout: int) -> dict:
    url = f"http://{ip}/ubus"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            log(f"POST /ubus → HTTP {resp.status} ({len(body)} bytes)")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"/ubus HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"/ubus unreachable: {e.reason}") from e


# ============ 业务逻辑 ============

def login_get_sid(ip: str, password: str, timeout: int) -> dict:
    """登录并获取 ubus_rpc_session。

    返回: {"sid": "32位hex", "expires": int, "username": "root"}
    异常: RuntimeError（网络错误 / 认证失败 / 协议错误）
    """
    # 前端 JS 硬编码 username="root"，密码 base64 编码
    pwd_b64 = base64.b64encode(password.encode("utf-8")).decode("ascii")
    log(f"登录 root/{password[:1]}*** (base64={pwd_b64[:4]}...)")

    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [ANON_SID, "session", "xapi_login",
                   {"username": "root", "password": pwd_b64}],
    }
    resp = ubus_call(ip, payload, timeout)

    result = resp.get("result")
    if not isinstance(result, list) or len(result) < 2:
        code = result[0] if isinstance(result, list) and len(result) > 0 else -1
        log(f"登录失败: code={code}")
        if code == 6:
            raise RuntimeError("密码错误 (ubus code=6)")
        raise RuntimeError(f"登录失败: code={code}, 响应={json.dumps(resp)}")

    rcode, rdata = result[0], result[1]
    if rcode != 0:
        raise RuntimeError(f"登录失败: code={rcode}")

    sid = rdata.get("ubus_rpc_session", "")
    if not sid or len(sid) != 32:
        raise RuntimeError(f"响应缺少 ubus_rpc_session: {json.dumps(rdata)}")

    log(f"登录成功: sid={sid}, expires={rdata.get('timeout')}s")
    return {
        "sid": sid,
        "expires": rdata.get("timeout", 300),
        "username": "root",
        "ip": ip,
    }


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="登录 Newifi/Lecoo 路由器并获取 ubus_rpc_session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 2.login_get_sid.py --pwd 12345678\n"
            "  python3 2.login_get_sid.py --ip 192.168.99.1 --pwd 12345678\n"
            "  python3 2.login_get_sid.py --pwd 12345678 --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--pwd", required=True,
                   help="管理员密码")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "登录 Newifi/Lecoo 路由器并获取 ubus_rpc_session "
                       "(密码 base64 编码，用户名固定 root)",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--pwd", "type": "string", "default": None,
             "required": True,
             "description": "管理员密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False,
             "description": f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 2.login_get_sid.py --pwd 12345678",
            "python3 2.login_get_sid.py --ip 192.168.99.1 --pwd 12345678",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 data.sid（32 位 hex token）的成功 JSON",
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
    ip = args.ip

    try:
        data = login_get_sid(ip, args.pwd, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        if "密码错误" in msg:
            emit_err(msg, reason="auth_failed", recoverable=True)
            return 4
        if "unreachable" in msg:
            emit_err(msg, reason="network_unreachable", recoverable=True)
            return 3
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
