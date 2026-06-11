#!/usr/bin/env python3
# cr660x/2.login_get_stok.py — CR660X 步骤 2：已初始化后登录拿 stok
#
# 适用机型: CR660X 系列（pb-boot 引导, 小米/红米体系）
# 前置: 路由器已初始化（跑过 1.official_init.py），工厂态会拒绝登录
#
# 流程: 扒 JS 拿 KEY → 探测 init_info → 校验 inited=1 → 登录（init=0）→ 输出 stok
#
# 输出: stdout = 单个 JSON {"ok":..., "step":..., "data"|"error":...}
#       stderr = 时间戳日志 (--debug 开启)
#       exit  = 0 成功 / 1 通用 / 4 认证

import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
STEP_NAME = "login_get_stok"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True,
             data: dict | None = None) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error}
    if reason:
        out["reason"] = reason
    if data is not None:
        out["data"] = data
    out["recoverable"] = recoverable
    print(json.dumps(out, ensure_ascii=False))


# ============ 扒 JS 拿 KEY ============
def fetch_key(ip: str, timeout: int) -> str:
    """pb-boot init.<hash>.js 里只有 KEY 字段（IV 不用）。"""
    log("扒取 init.<hash>.js 提取 KEY")
    html = http_get_raw(f"http://{ip}/init.html", timeout)
    m = re.search(r'/static/js/(init\.[a-f0-9]+\.js)', html)
    if not m:
        raise RuntimeError("未在 init.html 找到 init.*.js 引用")
    js_url = f"http://{ip}/static/js/{m.group(1)}"
    js = http_get_raw(js_url, timeout)
    key_m = re.search(r'\bkey\s*[:=]\s*["\']([0-9a-f]{32})["\']', js)
    if not key_m:
        raise RuntimeError("JS 里未找到 key 字段")
    return key_m.group(1)


# ============ 密码学 ============
def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def calc_login_password(nonce: str, pwd: str, key: str) -> str:
    """oldPwd = SHA1(nonce + SHA1(pwd + key)) — 联通/移动版通用。"""
    return sha1_hex(nonce + sha1_hex(pwd + key))


# ============ HTTP 基础 ============
def http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post(url: str, data: dict, timeout: int = 30) -> dict:
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_raw(url: str, timeout: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ============ variant 判定 ============
def detect_variant(info: dict) -> str:
    model = info.get("model", "").lower()
    if "cr6606" in model:
        return "unicom"
    if "cr6608" in model:
        return "move"
    if "cr6609" in model:
        return "vn"
    return "move"


# ============ 工厂态检测 ============
def is_factory_state(info: dict) -> bool:
    """True if the router is in factory (uninitialized) state."""
    return info.get("inited") == 0


# ============ 登录 ============
def login_unicom_initialized(router_ip: str, pwd: str, key: str, timeout: int) -> str:
    """CR6606 联通版已初始化：GET /login?init=0&..., 密码 = 用户密码。"""
    ts = int(time.time())
    nonce = f"0__{ts}_{random.randint(0, 9999)}"
    pwd_hash = calc_login_password(nonce, pwd, key)
    url = (f"http://{router_ip}/cgi-bin/luci/api/xqsystem/login"
           f"?username=admin&logtype=2&nonce={nonce}"
           f"&password={pwd_hash}&init=0")
    log(f"联通版 GET login (init=0): nonce={nonce}")
    result = http_get(url, timeout)
    if result.get("code") != 0:
        raise RuntimeError(
            f"联通版登录失败: {result.get('msg', result)} (code={result.get('code')})"
        )
    stok = result.get("token")
    if not stok:
        raise RuntimeError(f"联通版登录成功但未拿到 token: {result}")
    return stok


def login_move_initialized(router_ip: str, pwd: str, key: str,
                           device_id: str, timeout: int) -> str:
    """CR6608 移动/电信版已初始化：POST form-urlencoded, 密码 = 用户密码。"""
    ts = int(time.time())
    nonce = f"0_{device_id}_{ts}_{random.randint(0, 9999)}"
    pwd_hash = calc_login_password(nonce, pwd, key)
    url = f"http://{router_ip}/cgi-bin/luci/api/xqsystem/login"
    data = {
        "username": "admin",
        "password": pwd_hash,
        "logtype": "2",
        "nonce": nonce,
    }
    log(f"移动版 POST login: nonce={nonce}")
    result = http_post(url, data, timeout)
    if result.get("code") != 0:
        raise RuntimeError(
            f"移动版登录失败: {result.get('msg', result)} (code={result.get('code')})"
        )
    # 移动版 stok 从 url 字段 regex 提
    url_field = result.get("url", "")
    m = re.search(r";stok=([^/]+)", url_field)
    if m:
        return m.group(1)
    if result.get("token"):
        return result["token"]
    raise RuntimeError(f"移动版登录成功但未拿到 stok: {result}")


# ============ 主流程 ============
def login_get_stok(router_ip: str, pwd: str, variant_arg: str,
                   timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 1. 自举：扒 KEY
    key = fetch_key(router_ip, timeout)
    log(f"KEY={key[:8]}…")

    # 2. 探测 init_info（拿 inited + device_id + 判 variant）
    info = http_get(f"{base_url}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    if is_factory_state(info):
        raise RuntimeError(
            f"路由器出厂未初始化 (inited=0)，请先跑 1.official_init.py"
        )
    log(f"inited={info.get('inited')} model={info.get('model')}")

    device_id = info.get("id", "")
    detected_variant = detect_variant(info)
    variant = variant_arg if variant_arg != "auto" else detected_variant

    # 3. 登录
    if variant == "unicom":
        stok = login_unicom_initialized(router_ip, pwd, key, timeout)
    else:
        stok = login_move_initialized(router_ip, pwd, key, device_id, timeout)
    log("登录成功")

    return {
        "stok": stok, "ip": router_ip, "variant": variant,
        "model": info.get("model"), "inited": info.get("inited"),
        "key_source": "fetched from init.<hash>.js",
    }


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CR660X 步骤 2：已初始化后登录拿 stok（KEY 运行时扒）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # CR6606 联通版（自动探测 variant）\n"
            "  python3 2.login_get_stok.py --pwd mynewpass123\n"
            "  # CR6608 移动/电信版\n"
            "  python3 2.login_get_stok.py --ip 192.168.31.1 --pwd mynewpass123\n"
            "  # 强制 variant\n"
            "  python3 2.login_get_stok.py --variant unicom --pwd mynewpass123\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--variant", default="auto",
                   choices=["auto", "unicom", "move", "vn"],
                   help="强制 variant（默认 auto 走 init_info 探测）")
    p.add_argument("--pwd", required=True,
                   help="路由器管理密码（必传）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p.parse_args()


def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "CR660X 步骤 2：已初始化后登录拿 stok",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--variant", "type": "string", "default": "auto",
             "required": False, "description": "强制 variant (auto/unicom/move/vn)"},
            {"name": "--pwd", "type": "string", "default": None,
             "required": True, "description": "路由器管理密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 2.login_get_stok.py --pwd mynewpass123",
            "python3 2.login_get_stok.py --variant unicom --pwd mynewpass123",
        ],
        "stdin_contract": {"expects": "无", "produces": "含 stok 的成功 JSON"},
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug
    try:
        data = login_get_stok(args.ip, args.pwd, args.variant, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        err_msg = str(e)
        reason = "auth_failed" if "密码" in err_msg or "login" in err_msg.lower() else "unknown"
        if "inited=0" in err_msg or "工厂态" in err_msg:
            reason = "not_inited"
        emit_err(err_msg, reason=reason, recoverable=True)
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
