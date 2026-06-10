#!/usr/bin/env python3
# AX6 步骤 2：登录并获取 stok token
#
# 适用机型: Redmi AX6 (RA69) — IPQ8071A
# 加密: 运行时探测 newEncryptMode（0=SHA1, 1=SHA256）
# 探测: KEY / 加密模式从 init.html 引用的 init.<hash>.js 扒取；不写死任何密码学常量
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
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # 小米 DHCP 网关默认
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


def emit_err(error: str) -> None:
    print(json.dumps({"ok": False, "step": STEP_NAME, "error": error},
                     ensure_ascii=False))


# ============ 扒 JS 提取 KEY 和 newEncryptMode ============
def fetch_crypto_constants(ip: str, timeout: int) -> tuple[str, int]:
    """返回 (key, new_encrypt_mode)。KEY 仅用于登录哈希，不需 IV。"""
    log("扒取前端 JS 提取 KEY 和 newEncryptMode")
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
    mode_m = re.search(r'\bnewEncryptMode\s*[:=]\s*(\d+)', js)
    mode = int(mode_m.group(1)) if mode_m else 0
    return key_m.group(1), mode


# ============ 密码学（按 mode 选 SHA1 / SHA256） ============
def generate_nonce() -> str:
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def calc_login_password(nonce: str, pwd: str, key: str, mode: int) -> str:
    if mode == 1:
        return hashlib.sha256((nonce + _hex(hashlib.sha256, pwd + key)).encode()).hexdigest()
    return hashlib.sha1((nonce + _hex(hashlib.sha1, pwd + key)).encode()).hexdigest()


def _hex(algo, s: str) -> str:
    return algo(s.encode("utf-8")).hexdigest()


# ============ HTTP 基础 ============
def http_get_raw(url: str, timeout: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def http_get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 工厂态检测 ============
def is_factory_state(info: dict) -> bool:
    """True if the router is in factory (uninitialized) state.

    官方 init_info API 只暴露一个字段：
      - `inited=0` → "未初始化" → 出厂态
      - `inited=1` → "已初始化" → post-init

    （旧 shell 脚本里看到的 `init` 字段是脚本层从 inited 派生的便利字段，
    加上 -1 表示网络不可达——不是路由器给的。）
    """
    return info.get("inited") == 0


# ============ 主流程 ============
def login_get_stok(router_ip: str, admin_pwd: str, timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 自举：扒 JS 拿 KEY + 加密模式
    key, mode = fetch_crypto_constants(router_ip, timeout)
    log(f"newEncryptMode={mode}, KEY={key[:8]}…")

    # 前置校验：必须是已初始化状态
    info = http_get_json(f"{base_url}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    if is_factory_state(info):
        raise RuntimeError("路由器出厂未初始化，请先运行 1.official_init.py")
    log(f"已初始化状态确认 (inited={info.get('inited')})")

    # 登录（init=0 标志是已初始化阶段的会话登录）
    n = generate_nonce()
    pwd_hash = calc_login_password(n, admin_pwd, key, mode)
    login_url = (f"{base_url}/cgi-bin/luci/api/xqsystem/login"
                 f"?username=admin&logtype=2&nonce={n}"
                 f"&password={pwd_hash}&init=0")
    result = http_get_json(login_url, timeout)
    if result.get("code") != 0:
        code = result.get("code", "?")
        msg = result.get("msg", "no error message")
        raise RuntimeError(f"登录失败: {msg} (code={code})")
    stok = result["token"]
    log("登录成功")

    return {"stok": stok, "ip": router_ip, "encrypt_mode": mode,
            "key_source": "fetched from init.<hash>.js"}


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX6 步骤 2：登录并获取 stok（KEY / 加密模式运行时探测）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 2.login_get_stok.py\n"
            "  python3 2.login_get_stok.py --pwd adminpass123 --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--pwd", required=True,
                   help="管理员密码（必传，路由器没接口暴露当前密码）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug
    try:
        data = login_get_stok(args.ip, args.pwd, DEFAULT_TIMEOUT)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
