#!/usr/bin/env python3
# check_init.py — 探测 Newifi/Lecoo 路由器初始化状态
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 方法: 调用 xapi.basic.get_guide_status（无需认证）
#       status=0 → 未初始化（需走 1.lecco_init.py）
#       status=1 → 已初始化（需密码登录）
# 前置: 路由器 HTTP 服务可达
# 后置: 无副作用
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_TIMEOUT = 10
ANON_SID = "00000000000000000000000000000000"
STEP_NAME = "check_init"
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


def ubus_call(ip: str, payload: dict, timeout: int) -> dict:
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


def check_init(ip: str, timeout: int) -> dict:
    """探测路由器初始化状态，无副作用。"""
    log("探测 guide_status...")
    resp = ubus_call(ip, {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [ANON_SID, "xapi.basic", "get_guide_status", {}],
    }, timeout)
    log(f"get_guide_status → {json.dumps(resp)}")

    result = resp.get("result")
    guide_status = None
    if isinstance(result, list) and len(result) > 1:
        guide_status = result[1].get("status")

    if guide_status is None:
        raise RuntimeError(f"无法解析 guide_status: {json.dumps(resp)[:200]}")

    is_inited = (guide_status == 1)

    # 补充：尝试用默认密码登录，辅助判断
    import base64
    login_result = None
    try:
        pwd_b64 = base64.b64encode(b"admin").decode("ascii")
        login_resp = ubus_call(ip, {
            "jsonrpc": "2.0", "id": 2, "method": "call",
            "params": [ANON_SID, "session", "xapi_login",
                       {"username": "root", "password": pwd_b64}],
        }, timeout)
        login_code = None
        if isinstance(login_resp.get("result"), list) and len(login_resp["result"]) > 0:
            login_code = login_resp["result"][0]
        login_result = {
            "default_password_works": login_code == 0,
            "code": login_code,
        }
    except Exception as e:
        log(f"登录探测失败: {e}")

    return {
        "ip": ip,
        "is_inited": is_inited,
        "guide_status": guide_status,
        "default_login": login_result,
        "meaning": "未初始化（需运行 1.lecco_init.py）" if not is_inited
                   else "已初始化（需密码登录）",
    }


def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="探测 Newifi/Lecoo 路由器初始化状态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 check_init.py\n  python3 check_init.py --ip 192.168.99.1 --debug\n",
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "探测 Newifi/Lecoo 路由器初始化状态（无副作用，无需密码）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False,
             "description": f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 check_init.py",
            "python3 check_init.py --ip 192.168.99.1",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 is_inited/guide_status 的成功 JSON",
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
        data = check_init(args.ip, args.timeout)
    except RuntimeError as e:
        log(str(e), level="ERROR")
        if "连接失败" in str(e):
            emit_err(str(e), reason="network_unreachable", recoverable=True)
            return 3
        emit_err(str(e), recoverable=True)
        return 1
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), recoverable=True)
        return 1

    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
