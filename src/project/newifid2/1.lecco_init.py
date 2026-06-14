#!/usr/bin/env python3
# 1.lecco_init.py — Newifi/Lecoo 步骤 1：初始化路由器（设置管理密码）
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 前置: 路由器刚从恢复出厂设置重启（guide_status=0）
#       默认密码为 admin 或空
# 后置: 管理密码已设置，路由器可登录（guide_status → 1）
#       输出 data.sid = ubus_rpc_session（可 pip 到 2.login 复用）
#
# 流程: 检查 guide_status → 默认密码登录 → 设置新密码 → 验证
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络 / 4 认证

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_TIMEOUT = 15
DEFAULT_NEW_PWD = "12345678"
ANON_SID = "00000000000000000000000000000000"
STEP_NAME = "lecco_init"
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


def _call(ip: str, sid: str, obj: str, method: str,
          params: dict, timeout: int) -> tuple[int, dict]:
    """简化 ubus call，返回 (code, data_dict)。"""
    resp = ubus_call(ip, {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [sid, obj, method, params],
    }, timeout)
    result = resp.get("result")
    if not isinstance(result, list) or len(result) < 2:
        err = resp.get("error", {})
        code = err.get("code", -1)
        msg = err.get("message", str(resp)[:100])
        raise RuntimeError(f"{obj}.{method} 失败: {msg} (code={code})")
    return result[0], result[1]


def lecco_init(ip: str, new_password: str, timeout: int) -> dict:
    """执行初始化流程。"""
    log("=== 1. 探测 guide_status ===")
    code, data = _call(ip, ANON_SID, "xapi.basic", "get_guide_status",
                       {}, timeout)
    current_status = data.get("status", -1)
    log(f"guide_status = {current_status}")

    if current_status == 1:
        raise RuntimeError(
            "路由器已初始化 (guide_status=1)，不需要 init")

    if current_status != 0:
        raise RuntimeError(
            f"未知 guide_status={current_status}")

    log("路由器未初始化，开始设置管理密码")

    # 2. 尝试用默认密码登录
    #    出厂默认：前端硬编码 username="root"
    #    尝试各种默认密码
    log("=== 2. 尝试默认密码登录 ===")
    default_passwords = ["", "admin", "root", "password"]
    sid = None
    used_default_pwd = ""

    for default_pwd in default_passwords:
        pwd_b64 = base64.b64encode(default_pwd.encode()).decode("ascii")
        try:
            resp = ubus_call(ip, {
                "jsonrpc": "2.0", "id": 2, "method": "call",
                "params": [ANON_SID, "session", "xapi_login",
                           {"username": "root", "password": pwd_b64}],
            }, timeout)
            r = resp.get("result")
            if isinstance(r, list) and len(r) >= 2 and r[0] == 0:
                sid = r[1].get("ubus_rpc_session", "")
                used_default_pwd = default_pwd
                log(f"默认密码 '{default_pwd}' 登录成功: sid={sid[:16]}...")
                break
            log(f"默认密码 '{default_pwd}' → code={r[0] if r else '?'}")
        except Exception as e:
            log(f"默认密码 '{default_pwd}' 异常: {e}")

    if not sid:
        raise RuntimeError(
            "无法用任何默认密码登录 (尝试了: {})，"
            "路由器可能已被初始化或处于异常状态"
            .format(", ".join(repr(p) for p in default_passwords)),
        )

    # 3. 设置新密码（base64）
    log("=== 3. 设置管理密码 ===")
    new_b64 = base64.b64encode(new_password.encode()).decode("ascii")
    old_b64 = base64.b64encode(used_default_pwd.encode()).decode("ascii")

    # 用前端同样的 base64 接口
    code, data = _call(ip, sid, "xapi.sys", "set_login_passwd_base64",
                       {"old": old_b64, "new": new_b64,
                        "confirm": new_b64},
                       timeout)
    log(f"set_login_passwd_base64 → code={code}")
    if code != 0:
        raise RuntimeError(f"设置密码失败: code={code}")

    # 4. 验证：用新密码登录确认
    log("=== 4. 验证新密码 ===")
    time.sleep(1)
    new_b64 = base64.b64encode(new_password.encode()).decode("ascii")
    code, data = _call(ip, ANON_SID, "session", "xapi_login",
                       {"username": "root", "password": new_b64},
                       timeout)
    if code != 0:
        raise RuntimeError(
            f"新密码验证失败: code={code}，密码可能未正确设置")
    new_sid = data.get("ubus_rpc_session", "")
    log(f"新密码验证成功: sid={new_sid[:16]}...")

    # 5. 最终检查 guide_status 是否变为 1
    log("=== 5. 验证 guide_status ===")
    try:
        code, data = _call(ip, ANON_SID, "xapi.basic", "get_guide_status",
                           {}, timeout)
        final_status = data.get("status", -1)
        log(f"final guide_status = {final_status}")
    except Exception as e:
        log(f"重新检查 guide_status 失败: {e}")
        final_status = None

    return {
        "ip": ip,
        "sid": new_sid,
        "password": new_password,
        "guide_status_final": final_status,
        "init_complete": True,
    }


def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="初始化 Newifi/Lecoo 路由器（恢复出厂后设置管理密码）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 设置密码为 12345678\n"
            "  python3 1.lecco_init.py --pwd 12345678\n\n"
            "  # 自定义 IP\n"
            "  python3 1.lecco_init.py --ip 192.168.99.1 --pwd mypass\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--pwd", default=DEFAULT_NEW_PWD,
                   help=f"要设置的管理密码（默认: {DEFAULT_NEW_PWD}）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "初始化 Newifi/Lecoo 路由器（恢复出厂后设置管理密码）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--pwd", "type": "string", "default": DEFAULT_NEW_PWD,
             "required": False,
             "description": f"要设置的管理密码（默认: {DEFAULT_NEW_PWD}）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False,
             "description": f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 1.lecco_init.py --pwd 12345678",
            "python3 1.lecco_init.py --ip 192.168.99.1 --pwd mypass",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 sid（ubus_rpc_session）和 password 的成功 JSON",
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
        data = lecco_init(args.ip, args.pwd, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        if "已初始化" in msg:
            emit_err(msg, reason="already_inited", recoverable=False)
            return 1
        if "默认密码" in msg:
            emit_err(msg, reason="auth_failed", recoverable=True)
            return 4
        if "连接失败" in msg:
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
