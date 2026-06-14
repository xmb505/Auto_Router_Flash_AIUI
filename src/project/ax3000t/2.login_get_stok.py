#!/usr/bin/env python3
# AX3000T 步骤 2：登录并获取 stok token
#
# 适用机型: 小米路由器 AX3000T (RD03) — MediaTek Filogic 820 (MT7981)
# 加密: SHA256 (newEncryptMode=1)
# 探测: KEY 优先从 init.html 引用的 JS 扒取；失败回退到已知常量
#
# 与 AX5 的关键差异:
#   - HTTP 方法: POST form data（AX5 用 GET query string）
#   - 哈希: SHA256(nonce + SHA256(pwd + KEY))（AX5 用 SHA1）
#
# 前置: 路由器已初始化（运行过 1.official_init.py）。出厂态会拒绝登录。
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # 小米 DHCP 网关默认
DEFAULT_TIMEOUT = 30
STEP_NAME = "login_get_stok"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）

# AX3000T 已知 KEY（init.html JS 扒取失败时回退用）
KNOWN_KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ 扒 JS 提取 KEY（带回退） ============
def fetch_crypto_key(ip: str, timeout: int) -> tuple:
    """返回 (key, source)。优先扒 JS，失败回退已知常量。"""
    try:
        log("扒取前端 JS 提取 KEY")
        html = http_get_raw(f"http://{ip}/init.html", timeout)
        m = re.search(r'/static/js/(init\.[a-f0-9]+\.js)', html)
        if not m:
            raise RuntimeError("未在 init.html 找到 init.*.js 引用")
        js_url = f"http://{ip}/static/js/{m.group(1)}"
        log(f"抓取 {js_url}")
        js = http_get_raw(js_url, timeout)
        key_m = re.search(r'\bkey\s*:\s*"([0-9a-f]{32})"', js)
        if not key_m:
            raise RuntimeError("JS 里未找到 key 字段")
        return key_m.group(1), "fetched from init.<hash>.js"
    except Exception as e:
        log(f"扒 JS 失败 ({e})，回退到已知常量", level="WARN")
        return KNOWN_KEY, "hardcoded fallback (AX3000T known constant)"


# ============ 密码学（SHA256，newEncryptMode=1） ============
def generate_nonce() -> str:
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def calc_login_password(nonce: str, pwd: str, key: str) -> str:
    """SHA256(nonce + SHA256(pwd + KEY))"""
    return sha256_hex(nonce + sha256_hex(pwd + key))


# ============ HTTP 基础 ============
def http_get_raw(url: str, timeout: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def http_get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str, data: dict, timeout: int) -> dict:
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 工厂态检测 ============
def is_factory_state(info: dict) -> bool:
    """True if the router is in factory (uninitialized) state."""
    return info.get("inited") == 0


# ============ 主流程 ============
def login_get_stok(router_ip: str, admin_pwd: str, timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 自举：扒 JS 拿 KEY
    key, key_source = fetch_crypto_key(router_ip, timeout)
    log(f"KEY={key[:8]}…  source={key_source}")

    # 前置校验：必须是已初始化状态
    info = http_get_json(f"{base_url}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    if is_factory_state(info):
        raise RuntimeError("路由器出厂未初始化，请先运行 1.official_init.py")
    log(f"已初始化状态确认 (inited={info.get('inited')})")

    # 登录（AX3000T: POST + SHA256）
    n = generate_nonce()
    pwd_hash = calc_login_password(n, admin_pwd, key)
    login_url = f"{base_url}/cgi-bin/luci/api/xqsystem/login"
    result = http_post_json(login_url, {
        "username": "admin",
        "password": pwd_hash,
        "logtype": "2",
        "nonce": n,
    }, timeout)
    if result.get("code") != 0:
        code = result.get("code", "?")
        msg = result.get("msg", "no error message")
        raise RuntimeError(f"登录失败: {msg} (code={code})")
    stok = result["token"]
    log("登录成功")

    return {"stok": stok, "ip": router_ip,
            "encrypt_mode": 1, "key_source": key_source}


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "login_get_stok",
        "description": "AX3000T 步骤 2：登录并获取 stok（POST + SHA256）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--pwd", "type": "string", "default": None,
             "required": True, "description": "管理员密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 2.login_get_stok.py --pwd adminpass123",
            "python3 2.login_get_stok.py --pwd adminpass123 --debug",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 data.stok 的成功 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3000T 步骤 2：登录并获取 stok（POST + SHA256）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 2.login_get_stok.py --pwd adminpass123\n"
            "  python3 2.login_get_stok.py --pwd adminpass123 --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--pwd", required=True,
                   help="管理员密码（必传，路由器没接口暴露当前密码）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug
    try:
        data = login_get_stok(args.ip, args.pwd, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
