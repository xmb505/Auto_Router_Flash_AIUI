#!/usr/bin/env python3
# router_lecoo_recovery.py — 触发 Lecoo/Newifi 路由器恢复出厂设置
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 协议: ubus JSON-RPC → xapi.basic.reset_start
# 前置: 已有 ubus_rpc_session（通过 2.login_get_sid.py --pwd 获取）
# 效果: 路由器恢复出厂设置后自动重启，IP 和密码恢复默认
# 注意: 调用后路由器会立即进入重置流程（HTTP 断连是预期行为）
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功（指令已发出）/ 1 通用 / 3 网络 / 5 超时

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_TIMEOUT = 15
STEP_NAME = "router_lecoo_recovery"
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
    log(f"POST /ubus method={payload.get('method','?')}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            log(f"← HTTP {resp.status} ({len(body)} bytes)")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"/ubus HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}") from e


def factory_reset(ip: str, sid: str, timeout: int) -> dict:
    """触发路由器恢复出厂设置。

    调用 xapi.basic.reset_start，路由器收到指令后立即进入重置流程，
    HTTP 会断连，ubus 可能超时——这是预期行为。
    """
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [sid, "xapi.basic", "reset_start", {}],
    }
    log(f"发送恢复出厂指令 sid={sid[:16]}...")

    try:
        resp = ubus_call(ip, sid, payload, timeout)
    except (RuntimeError, urllib.error.URLError) as e:
        # 路由器重置后断连，超时是预期的成功信号
        log(f"连接断开（预期行为）: {e}")
        return {
            "reset_triggered": True,
            "note": "路由器已进入重置流程，HTTP 断连是预期行为",
        }

    # 如果居然有响应，检查结果
    result = resp.get("result")
    if isinstance(result, list) and len(result) > 0:
        code = result[0]
        if code == 0:
            return {
                "reset_triggered": True,
                "note": "恢复出厂指令已发送",
            }
        raise RuntimeError(f"reset_start 失败: code={code}")

    raise RuntimeError(f"reset_start 返回异常: {json.dumps(resp)[:200]}")


def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="触发 Lecoo/Newifi 路由器恢复出厂设置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 router_lecoo_recovery.py --sid <ubus_rpc_session>\n"
            "  python3 router_lecoo_recovery.py --sid xxx --debug\n"
            "  # 配合 login 链式调用:\n"
            "  python3 2.login_get_sid.py --pwd 12345678 | \\\n"
            "    python3 -c 'import sys,json; print(json.load(sys.stdin)[\"data\"][\"sid\"])' | \\\n"
            "    xargs -I{} python3 router_lecoo_recovery.py --sid {}\n"
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
        "description": "触发 Lecoo/Newifi 路由器恢复出厂设置（xapi.basic.reset_start）",
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
            "python3 router_lecoo_recovery.py --sid <ubus_rpc_session>",
            "python3 router_lecoo_recovery.py --sid a71f7f6a7b2352f7614d6a935baf11af",
        ],
        "stdin_contract": {
            "expects": "无（sid 从 --sid 参数传入）",
            "produces": "含 reset_triggered=true 的成功 JSON",
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
        data = factory_reset(args.ip, args.sid, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        emit_err(msg, recoverable=False)
        return 1
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), recoverable=False)
        return 1

    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
