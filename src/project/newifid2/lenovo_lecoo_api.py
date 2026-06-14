#!/usr/bin/env python3
# lenovo_lecoo_api.py — 调用 Lecoo/Newifi ubus API，原样打印路由器 JSON 响应
#
# 探测内容（无需密码）：
#   1) /ubus method=list        → 所有可用 RPC 对象
#   2) xapi.basic.get_version   → 固件版本
#   3) session.access           → 匿名 session 权限
#   4) session.xapi_login       → 登录尝试（判断是否已初始化）
#
# 输出: stdout = 路由器原始 JSON 响应（按探测顺序依次打印）
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络

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
DEBUG = False


def log(msg: str) -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [INFO] {msg}", file=sys.stderr)


def ubus(ip: str, payload: dict, timeout: int) -> dict:
    """POST /ubus，返回路由器原始 JSON 响应。"""
    url = f"http://{ip}/ubus"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    req.add_header("Content-Type", "application/json")
    label = payload.get("method", payload.get("params", [{}])[0:2])
    log(f"POST /ubus {label}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            log(f"← HTTP {resp.status} ({len(body)} bytes)")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"/ubus HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"/ubus unreachable: {e.reason}") from e


def main() -> int:
    global DEBUG
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--ip", default=DEFAULT_IP)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--debug", action="store_true")
    args, _ = p.parse_known_args()
    DEBUG = args.debug

    ip = args.ip
    timeout = args.timeout

    probes = [
        ("RPC 对象列表", {"jsonrpc": "2.0", "id": 1, "method": "list"}),
        ("固件版本", {"jsonrpc": "2.0", "id": 2, "method": "call",
                      "params": [ANON_SID, "xapi.basic", "get_version", {}]}),
        ("session 权限", {"jsonrpc": "2.0", "id": 3, "method": "call",
                         "params": [ANON_SID, "session", "access",
                                    {"scope": "ubus", "object": "session",
                                     "function": "access"}]}),
        ("登录尝试(root/base64(admin))", {"jsonrpc": "2.0", "id": 4, "method": "call",
                                   "params": [ANON_SID, "session", "xapi_login",
                                              {"username": "root",
                                               "password": base64.b64encode(b"admin").decode()}]}),
    ]

    results = []
    for label, payload in probes:
        try:
            resp = ubus(ip, payload, timeout)
            results.append({"label": label, "raw": resp})
        except RuntimeError as e:
            log(f"{label} 失败: {e}")
            sys.exit(3)

    # 原样输出：每个 API 的原始 JSON 响应
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
