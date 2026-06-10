#!/usr/bin/env python3
# AX6 出厂初始化向导（刷机前置步骤 1）
#
# 适用机型: Redmi AX6 (RA69) — IPQ8071A, newEncryptMode=0 (SHA1)
# 默认 IP:  192.168.31.1
#
# 流程: 扒 JS 提取 KEY/IV → 探测 → 登录 → WAN → 禁更新 → 设 Wi-Fi/管理密码
# 实现: 复刻 old_coding/Auto_Flash_Router/AX6/auto_init.py，仅 KEY/IV 来源改为运行时扒 JS
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 时间戳日志
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


# ============ 扒 JS 提取 KEY/IV ============
def fetch_crypto_constants(ip: str, timeout: int) -> tuple[str, str]:
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
    return key_m.group(1), iv_m.group(1)


# ============ 密码学（参数化 KEY/IV，算法跟老版本字面相同） ============
def generate_nonce() -> str:
    """老版本格式: 0__{ts}_{rand}（mac 字段始终为空，未登录时前端 cookie 无 mac）"""
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def calc_login_password(nonce: str, pwd: str, key: str) -> str:
    return sha1_hex(nonce + sha1_hex(pwd + key))


def calc_new_pwd(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    aes_key = bytes.fromhex(sha1_hex(old_pwd + key)[:32])
    plain = sha1_hex(new_pwd + key).encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()


# ============ HTTP 基础（跟老版本 urllib 实现一致） ============
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


def need_bw160(version: str) -> bool:
    try:
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1])
        return major >= 1 and minor >= 1
    except (ValueError, IndexError):
        return True


# ============ 主流程（复刻老版本 auto_init，参数化 KEY/IV） ============
def official_init(router_ip: str, ssid: str, wifi_pwd: str, admin_pwd: str,
                  timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # 自举：扒 JS 拿 KEY/IV
    key, iv = fetch_crypto_constants(router_ip, timeout)
    log(f"KEY={key[:8]}…  IV={iv[:8]}…")

    # Step 0: 固件版本 + 默认 SSID（前端 chunk_14.js 用 a.data.name，但未登录的
    #         init_info 阶段只能拿 routername——作为 SSID 兜底）
    info = http_get(f"http://{router_ip}/cgi-bin/luci/api/xqsystem/init_info", timeout)
    fw_ver = info.get("romversion", "")
    default_ssid = info.get("routername") or info.get("name") or ""
    has_bw160 = need_bw160(fw_ver)
    if not ssid:
        if default_ssid:
            ssid = default_ssid
            log(f"使用路由器返回的 SSID: {ssid}")
        else:
            raise RuntimeError("未传 --ssid 且路由器未返回 routername，请显式指定")
    log(f"固件 {fw_ver}, bw160={has_bw160}")

    # Step 1: 登录（newEncryptMode=0: SHA1 双哈希，GET 形式）
    login_nonce = generate_nonce()
    login_pwd = calc_login_password(login_nonce, "admin", key)
    login_url = (f"{base_url}/cgi-bin/luci/api/xqsystem/login"
                 f"?username=admin&logtype=2&nonce={login_nonce}"
                 f"&password={login_pwd}&init=1&privacy=1")
    result = http_get(login_url, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"登录失败: {result}")
    stok = result["token"]
    log("登录成功")

    # Step 2: WAN = DHCP
    wan_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"
    result = http_post(wan_url, {"wanType": "dhcp", "autoset": "0"}, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"设置 WAN 失败: {result}")
    log("WAN 已设为 DHCP")

    # Step 3: 禁用自动更新
    upgrade_url = (f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/vas_switch"
                   f"?info=auto_upgrade%3D0")
    result = http_get(upgrade_url, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"禁用自动更新失败: {result}")
    log("已禁用自动更新")

    # Step 4: 设 Wi-Fi + 管理密码
    set_nonce = generate_nonce()
    old_pwd_hash = calc_login_password(set_nonce, "admin", key)
    new_pwd_hash = calc_new_pwd("admin", admin_pwd, key, iv)
    post_data = {
        "name": ssid, "locale": "家", "ssid": ssid, "password": wifi_pwd,
        "encryption": "mixed-psk", "nonce": set_nonce,
        "newPwd": new_pwd_hash, "oldPwd": old_pwd_hash, "txpwr": "1",
        "routerPwd": admin_pwd,
    }
    if has_bw160:
        post_data["bw160"] = "false"
    set_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_router_normal"
    result = http_post(set_url, post_data, timeout=30)
    if result.get("code") != 0:
        raise RuntimeError(f"设置 Wi-Fi/管理密码失败: {result}")
    log("Wi-Fi 与管理密码设置完成")

    return {"stok": stok, "ip": result.get("ip", router_ip), "ssid": ssid,
            "firmware_version": fw_ver, "key_source": "fetched from init.<hash>.js"}


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX6 出厂初始化（刷机前置步骤 1）— KEY/IV 从网页扒",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 1.official_init.py --admin-pwd 12345678\n"
        ),
    )
    p.add_argument("--router", default=DEFAULT_ROUTER_IP,
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
    args = parse_args()
    DEBUG = args.debug
    if not args.wifi_pwd:
        args.wifi_pwd = args.admin_pwd
        log("未传 --wifi-pwd，默认使用 --admin-pwd")
    try:
        data = official_init(args.router, args.ssid, args.wifi_pwd,
                             args.admin_pwd, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
