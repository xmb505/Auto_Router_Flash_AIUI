#!/usr/bin/env python3
# AX3000T 出厂初始化向导（刷机前置步骤 1）
#
# 适用机型: 小米路由器 AX3000T (RD03) — MediaTek Filogic 820 (MT7981)
# 加密: newEncryptMode=1 (SHA256)
# 默认 IP: 192.168.31.1
#
# 与 AX5 的关键差异:
#   - 出厂登录: GET 明文 password=admin&init=1（无需 nonce）
#   - WAN 设置: POST autoset=1（AX5 用 autoset=0）
#   - 密码哈希: SHA256 oldPwd + newPwd(SHA1-AES) + newPwd256(SHA256-AES)
#   - set_router_normal 额外字段: update=1, bw160=1, bsd=1
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import base64
import hashlib
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from Crypto.Cipher import AES

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # 小米 DHCP 网关默认
DEFAULT_TIMEOUT = 30
STEP_NAME = "official_init"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）

# AX3000T 已知密码学常量（KEY/IV），init.html JS 扒取失败时回退用
KNOWN_KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
KNOWN_IV = "64175472480004614961023454661220"
FACTORY_PWD = "admin"  # 出厂默认管理员密码


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


# ============ 扒 JS 提取 KEY/IV（带回退） ============
def fetch_crypto_constants(ip: str, timeout: int) -> tuple:
    """返回 (key, iv, source)。优先扒 JS，失败回退已知常量。"""
    try:
        log("扒取前端 JS 提取 KEY/IV")
        html = http_get_raw(f"http://{ip}/init.html", timeout)
        m = re.search(r'/static/js/(init\.[a-f0-9]+\.js)', html)
        if not m:
            raise RuntimeError("未在 init.html 找到 init.*.js 引用")
        js_url = f"http://{ip}/static/js/{m.group(1)}"
        log(f"抓取 {js_url}")
        js = http_get_raw(js_url, timeout)
        key_m = re.search(r'\bkey\s*:\s*"([0-9a-f]{32})"', js)
        iv_m = re.search(r'\biv\s*:\s*"([0-9a-f]{32})"', js)
        if not key_m or not iv_m:
            raise RuntimeError("JS 里未找到 key/iv 字段")
        return key_m.group(1), iv_m.group(1), "fetched from init.<hash>.js"
    except Exception as e:
        log(f"扒 JS 失败 ({e})，回退到已知常量", level="WARN")
        return KNOWN_KEY, KNOWN_IV, "hardcoded fallback (AX3000T known constants)"


# ============ 密码学 ============
def generate_nonce() -> str:
    """老版本格式: 0__{ts}_{rand}"""
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def calc_old_pwd(nonce: str, old_pwd: str, key: str) -> str:
    """计算 oldPwd: SHA256(nonce + SHA256(old_pwd + KEY)) (newEncryptMode=1)"""
    inner = sha256_hex(old_pwd + key)
    return sha256_hex(nonce + inner)


def calc_new_pwd(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    """计算 newPwd (AES-CBC, SHA1 密钥派生) — 兼容旧模式"""
    aes_key = bytes.fromhex(sha1_hex(old_pwd + key)[:32])
    plain = sha1_hex(new_pwd + key).encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()


def calc_new_pwd256(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    """计算 newPwd256 (AES-CBC, SHA256 密钥派生) — newEncryptMode=1"""
    aes_key = bytes.fromhex(sha256_hex(old_pwd + key)[:32])
    plain = sha256_hex(new_pwd + key).encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()


# ============ HTTP 基础 ============
def http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def http_post(url: str, data: dict, timeout: int = 30) -> dict:
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def http_get_raw(url: str, timeout: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ============ 主流程 ============
def official_init(router_ip: str, ssid: str, wifi_pwd: str, admin_pwd: str,
                  timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 自举：扒 JS 拿 KEY/IV（失败回退已知常量）
    key, iv, key_source = fetch_crypto_constants(router_ip, timeout)
    log(f"KEY={key[:8]}…  IV={iv[:8]}…  source={key_source}")

    # Step 0: 固件版本 + 默认 SSID
    info = http_get(f"http://{router_ip}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    fw_ver = info.get("romversion", "")
    default_ssid = info.get("routername") or info.get("name") or ""
    if not ssid:
        if default_ssid:
            ssid = default_ssid
            log(f"使用路由器返回的 SSID: {ssid}")
        else:
            raise RuntimeError("未传 --ssid 且路由器未返回 routername，请显式指定")
    log(f"固件 {fw_ver}")

    # Step 1: 登录（AX3000T newEncryptMode=1: 出厂态 GET 明文密码 + init=1）
    login_url = (f"{base_url}/cgi-bin/luci/api/xqsystem/login"
                 f"?username=admin&logtype=2&password={FACTORY_PWD}&init=1")
    result = http_get(login_url, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"登录失败: {result}")
    stok = result["token"]
    log("出厂登录成功")

    # Step 2: WAN = DHCP（POST 方式，AX3000T 用 autoset=1）
    wan_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"
    result = http_post(wan_url, {"wanType": "dhcp", "autoset": "1"}, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"设置 WAN 失败: {result}")
    log("WAN 已设为 DHCP")

    # Step 3: 禁用自动更新
    upgrade_url = (f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/vas_switch"
                   f"?info=auto_upgrade%3D0")
    result = http_get(upgrade_url, timeout)
    if result.get("code") != 0:
        log(f"禁用自动更新失败（非阻塞）: {result}", level="WARN")
    else:
        log("已禁用自动更新")

    # Step 4: 设 Wi-Fi + 管理密码（AX3000T: SHA256 oldPwd + newPwd + newPwd256）
    nonce = generate_nonce()
    old_pwd_hash = calc_old_pwd(nonce, FACTORY_PWD, key)          # SHA256
    new_pwd_enc = calc_new_pwd(FACTORY_PWD, admin_pwd, key, iv)   # SHA1-AES (兼容)
    new_pwd256_enc = calc_new_pwd256(FACTORY_PWD, admin_pwd, key, iv)  # SHA256-AES

    post_data = {
        "ssid": ssid,
        "password": wifi_pwd,
        "name": ssid,
        "locale": "家",
        "encryption": "mixed-psk",
        "txpwr": "1",
        "update": "1",
        "bw160": "1",
        "bsd": "1",
        "nonce": nonce,
        "oldPwd": old_pwd_hash,
        "newPwd": new_pwd_enc,
        "newPwd256": new_pwd256_enc,
        "routerPwd": admin_pwd,
    }
    set_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_router_normal"
    result = http_post(set_url, post_data, timeout=30)
    if result.get("code") != 0:
        raise RuntimeError(f"设置 Wi-Fi/管理密码失败: {result}")
    log("Wi-Fi 与管理密码设置完成")

    return {"stok": stok, "ip": result.get("ip", router_ip), "ssid": ssid,
            "firmware_version": fw_ver, "key_source": key_source}


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "official_init",
        "description": "AX3000T 出厂初始化（刷机前置步骤 1）— SHA256 密码学 + newPwd256",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--ssid", "type": "string", "default": "",
             "required": False, "description": "Wi-Fi SSID（默认从路由器 init_info 抓）"},
            {"name": "--wifi-pwd", "type": "string", "default": "",
             "required": False, "description": "Wi-Fi 密码（默认等于 --admin-pwd）"},
            {"name": "--admin-pwd", "type": "string", "default": None,
             "required": True, "description": "管理员密码（必传，初始化时新设）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 1.official_init.py --admin-pwd 12345678",
            "python3 1.official_init.py --admin-pwd 12345678 --debug",
        ],
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3000T 出厂初始化（刷机前置步骤 1）— SHA256 + newPwd256",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 1.official_init.py --admin-pwd 12345678\n"
            "  python3 1.official_init.py --admin-pwd 12345678 --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--ssid", default="",
                   help="Wi-Fi SSID（默认从路由器 init_info 抓）")
    p.add_argument("--wifi-pwd", default="",
                   help="Wi-Fi 密码（默认等于 --admin-pwd）")
    p.add_argument("--admin-pwd", required=True,
                   help="管理员密码（必传，初始化时新设）")
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
    if not args.wifi_pwd:
        args.wifi_pwd = args.admin_pwd
        log("未传 --wifi-pwd，默认使用 --admin-pwd")
    try:
        data = official_init(args.ip, args.ssid, args.wifi_pwd,
                             args.admin_pwd, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
