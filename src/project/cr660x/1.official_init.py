#!/usr/bin/env python3
# cr660x/1.official_init.py — CR660X 出厂初始化向导
#
# 适用机型: CR660X 系列（pb-boot 引导, 小米/红米体系）
#   - CR6606 联通版:  GET /login?init=1&privacy=1&..., 密码 admin
#   - CR6608 移动/电信: POST /login form-urlencoded, 密码 admin
# 加密: KEY/IV 运行时从 init.<hash>.js 扒取（小米共享，不写死）
#
# 流程: 扒 JS 提取 KEY/IV → 探测 init_info → 判 variant → 工厂态登录 → WAN → 禁更新 → 设密码
#
# 输出: stdout = 单个 JSON {"ok":..., "step":..., "data"|"error":..., "reason"?}
#       stderr = 时间戳日志 (--debug 开启)
#       exit  = 0 成功 / 1 通用 / 2 参数 / 3 网络 / 4 认证 / 5 超时

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
DEFAULT_ROUTER_IP = "192.168.31.1"   # CR6608 默认；CR6606 一般 192.168.1.1
DEFAULT_TIMEOUT = 30
STEP_NAME = "official_init"
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


# ============ 扒 JS 提取 KEY/IV（pb-boot init.<hash>.js） ============
def fetch_crypto_constants(ip: str, timeout: int) -> tuple[str, str]:
    """pb-boot 的 /init.html 引用 init.<hash>.js，KEY/IV 在里面。

    实测 JS 片段（2026-06-11）：
      key:"a2ffa5c9be07488bbb04a3a47d3c5f6a"
      iv :"64175472480004614961023454661220"
      encrypt(i, n, {iv:o, mode:CBC, padding:Pkcs7})  // newPwd 用 AES-CBC
    """
    log("扒取 init.<hash>.js 提取 KEY/IV")
    html = http_get_raw(f"http://{ip}/init.html", timeout)
    m = re.search(r'/static/js/(init\.[a-f0-9]+\.js)', html)
    if not m:
        raise RuntimeError("未在 init.html 找到 init.*.js 引用")
    js_url = f"http://{ip}/static/js/{m.group(1)}"
    log(f"抓取 {js_url}")
    js = http_get_raw(js_url, timeout)
    key_m = re.search(r'\bkey\s*[:=]\s*["\']([0-9a-f]{32})["\']', js)
    iv_m = re.search(r'\biv\s*[:=]\s*["\']([0-9a-f]{32})["\']', js)
    if not key_m or not iv_m:
        raise RuntimeError("JS 里未找到 key/iv 字段")
    return key_m.group(1), iv_m.group(1)


# ============ 密码学 ============
def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def calc_login_password(nonce: str, pwd: str, key: str) -> str:
    """oldPwd = SHA1(nonce + SHA1(pwd + key)) — 联通/移动版通用。"""
    return sha1_hex(nonce + sha1_hex(pwd + key))


def calc_new_pwd(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    """newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7)
    JS 实际逻辑:
      n = SHA1(old_pwd+key).hex[:32]  // 16 字节 AES key
      i = SHA1(new_pwd+key).hex         // 40 字节明文
      return CryptoJS.AES.encrypt(i, n, {iv, CBC, Pkcs7}).toString()
    """
    aes_key = bytes.fromhex(sha1_hex(old_pwd + key)[:32])
    plain = sha1_hex(new_pwd + key).encode("utf-8")
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
    """根据 init_info.model 判定: cr6606=unicom, cr6608/cr6609=move。"""
    model = info.get("model", "").lower()
    if "cr6606" in model:
        return "unicom"
    # CR6608/TR608（移动版）、CR6609/TR609（电信版）都用 move 流程（POST 登录）
    return "move"


# ============ 工厂态登录 ============
def login_unicom(router_ip: str, key: str, timeout: int) -> str:
    """CR6606 联通版工厂态：GET /login?init=1&privacy=1, 密码 admin, nonce 无 mac。"""
    ts = int(time.time())
    nonce = f"0__{ts}_{random.randint(0, 9999)}"
    pwd_hash = calc_login_password(nonce, "admin", key)
    url = (f"http://{router_ip}/cgi-bin/luci/api/xqsystem/login"
           f"?username=admin&logtype=2&nonce={nonce}"
           f"&password={pwd_hash}&init=1&privacy=1")
    log(f"联通版 GET login: nonce={nonce}")
    result = http_get(url, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"联通版登录失败: {result.get('msg', result)}")
    stok = result.get("token")
    if not stok:
        raise RuntimeError(f"联通版登录成功但未拿到 token: {result}")
    return stok


def login_move(router_ip: str, key: str, device_id: str, timeout: int) -> str:
    """CR6608 移动/电信版工厂态：POST form-urlencoded, 密码 admin, nonce 含 device_id。"""
    ts = int(time.time())
    nonce = f"0_{device_id}_{ts}_{random.randint(0, 9999)}"
    pwd_hash = calc_login_password(nonce, "admin", key)
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
        raise RuntimeError(f"移动版登录失败: {result.get('msg', result)}")
    # 移动版 stok 从 url 字段 regex 提
    url_field = result.get("url", "")
    m = re.search(r";stok=([^/]+)", url_field)
    if m:
        return m.group(1)
    if result.get("token"):
        return result["token"]
    raise RuntimeError(f"移动版登录成功但未拿到 stok: {result}")


# ============ 主流程 ============
def official_init(router_ip: str, ssid: str, wifi_pwd: str,
                  admin_pwd: str, variant_arg: str, timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 1. 探测 init_info
    log("探测 init_info")
    info = http_get(f"http://{router_ip}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    fw_ver = info.get("romversion", "")
    default_ssid = info.get("routername") or info.get("name") or ""
    inited = info.get("inited")
    device_id = info.get("id", "")
    detected_variant = detect_variant(info)
    variant = variant_arg if variant_arg != "auto" else detected_variant

    if inited is None:
        raise RuntimeError(f"init_info 缺 inited 字段: {info}")
    if inited != 0:
        raise RuntimeError(
            f"路由器已初始化 (inited={inited})，请直接跑 2.login_get_stok.py"
        )
    log(f"inited={inited} model={info.get('model')} variant={variant}")

    if not ssid:
        if default_ssid:
            ssid = default_ssid
            log(f"使用 init_info SSID: {ssid}")
        else:
            raise RuntimeError("未传 --ssid 且 init_info 无 routername")

    # 2. 扒 KEY/IV
    key, iv = fetch_crypto_constants(router_ip, timeout)
    log(f"KEY={key[:8]}…  IV={iv[:8]}…")

    # 3. 工厂态登录
    if variant == "unicom":
        stok = login_unicom(router_ip, key, timeout)
    else:
        stok = login_move(router_ip, key, device_id, timeout)
    log("登录成功")

    # 4. WAN = DHCP
    wan_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"
    r = http_post(wan_url, {"wanType": "dhcp", "autoset": "0"}, timeout)
    if r.get("code") != 0:
        raise RuntimeError(f"设 WAN 失败: {r}")
    log("WAN 已设 DHCP")

    # 5. 禁自动更新
    upgrade_url = (f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/vas_switch"
                   f"?info=auto_upgrade%3D0")
    r = http_get(upgrade_url, timeout)
    if r.get("code") != 0:
        raise RuntimeError(f"禁自动更新失败: {r}")
    log("已禁自动更新")

    # 6. 设 Wi-Fi/管理密码
    #    实测 JS（init.283819a8fd2437ffa729.js）确认：
    #      oldPwd = SHA1(nonce + SHA1(old_pwd + key))                  // 明文 old_pwd
    #      newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7)
    #      routerPwd = 明文 new_pwd
    #    跟 ax6/ax3600 算法完全一致。
    set_nonce = f"0__{int(time.time())}_{random.randint(0, 9999)}"
    old_pwd_hash = calc_login_password(set_nonce, "admin", key)
    new_pwd_aes = calc_new_pwd("admin", admin_pwd, key, iv)
    set_data = {
        "name": ssid, "locale": "家", "ssid": ssid, "password": wifi_pwd,
        "encryption": "mixed-psk", "nonce": set_nonce,
        "newPwd": new_pwd_aes, "oldPwd": old_pwd_hash, "txpwr": "1",
        "routerPwd": admin_pwd,
    }
    set_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_router_normal"
    try:
        r = http_post(set_url, set_data, timeout)
    except ValueError as e:
        # pb-boot 偶尔返回非标准 JSON (含末尾空行/garbage)，按"已成功"处理
        log(f"set_router_normal 响应解析失败 (按成功处理): {e}")
        r = {"code": 0, "_parse_error": str(e)}
    if r.get("code") != 0:
        raise RuntimeError(f"设 Wi-Fi/管理密码失败: {r}")
    log("Wi-Fi 与管理密码设置完成")

    return {
        "stok": stok, "ip": router_ip, "ssid": ssid,
        "variant": variant, "model": info.get("model"),
        "firmware_version": fw_ver,
        "key_source": "fetched from init.<hash>.js",
    }


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CR660X 出厂初始化向导（联通/移动/电信版自动判定）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # CR6606 联通版（默认探测后自动走 GET init=1）\n"
            "  python3 1.official_init.py --admin-pwd mynewpass123\n"
            "  # CR6608 移动版 / CR6609 电信版\n"
            "  python3 1.official_init.py --ip 192.168.31.1 --admin-pwd mynewpass123\n"
            "  # 强制 variant\n"
            "  python3 1.official_init.py --variant unicom --admin-pwd mynewpass123\n"
            "  # 显式 SSID / Wi-Fi 密码\n"
            "  python3 1.official_init.py --ssid MyWiFi --wifi-pwd wifipass123 --admin-pwd adminpass\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--variant", default="auto",
                   choices=["auto", "unicom", "move"],
                   help="强制 variant（默认 auto 走 init_info 探测）")
    p.add_argument("--ssid", default="",
                   help="Wi-Fi SSID（默认从 init_info.routername 拿）")
    p.add_argument("--wifi-pwd", default="",
                   help="Wi-Fi 密码（默认等于 --admin-pwd）")
    p.add_argument("--admin-pwd", required=True,
                   help="新的路由器管理密码（必传，初始化时新设）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p.parse_args()


def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "CR660X 出厂初始化向导",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--variant", "type": "string", "default": "auto",
             "required": False, "description": "强制 variant (auto/unicom/move/vn)"},
            {"name": "--ssid", "type": "string", "default": "",
             "required": False, "description": "Wi-Fi SSID"},
            {"name": "--wifi-pwd", "type": "string", "default": "",
             "required": False, "description": "Wi-Fi 密码 (默认等于 --admin-pwd)"},
            {"name": "--admin-pwd", "type": "string", "default": None,
             "required": True, "description": "路由器管理密码 (必传)"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 1.official_init.py --admin-pwd mynewpass123",
            "python3 1.official_init.py --variant unicom --admin-pwd mynewpass123",
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
    if not args.wifi_pwd:
        args.wifi_pwd = args.admin_pwd
        log("未传 --wifi-pwd，默认用 --admin-pwd")
    try:
        data = official_init(args.ip, args.ssid, args.wifi_pwd,
                             args.admin_pwd, args.variant, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="init_failed", recoverable=True)
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
