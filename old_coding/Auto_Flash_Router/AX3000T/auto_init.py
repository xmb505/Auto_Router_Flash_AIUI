#!/usr/bin/env python3
"""
小米 AX3000T 路由器 自动初始化（刷机前置）脚本

适用机型:
    - 小米路由器 AX3000T (RD03)
    - 出厂固件版本 1.0.64
    - newEncryptMode = 1 (SHA256 加密)

用法:
    python3 auto_init.py [--ip IP] [--ssid SSID] [--wifi-pwd PWD] [--admin-pwd PWD]
    python3 auto_init.py [--help]
"""

import hashlib
import base64
import random
import time
import urllib.parse
import urllib.request
import json
import sys
import argparse

from Crypto.Cipher import AES

# ============ 常量 ============
KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
IV = "64175472480004614961023454661220"
FACTORY_PWD = "admin"  # 出厂默认管理员密码


def generate_nonce():
    """生成 nonce: 0__[timestamp]_[random]（旧格式，双下划线）"""
    ts = int(time.time())
    rand = random.randint(0, 9999)
    return f"0__{ts}_{rand}"


def sha1_hex(s: str) -> str:
    """SHA1 hex 摘要"""
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def sha256_hex(s: str) -> str:
    """SHA256 hex 摘要"""
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def calc_old_pwd(nonce: str, old_pwd: str) -> str:
    """计算 oldPwd: SHA256(nonce + SHA256(old_pwd + KEY)) (newEncryptMode=1)"""
    inner = sha256_hex(old_pwd + KEY)
    return sha256_hex(nonce + inner)


def calc_new_pwd(old_pwd: str, new_pwd: str) -> str:
    """计算 newPwd (AES-CBC, SHA1 密钥派生) — 兼容旧模式"""
    aes_key_hex = sha1_hex(old_pwd + KEY)[:32]
    aes_key = bytes.fromhex(aes_key_hex)
    plain_hash = sha1_hex(new_pwd + KEY)
    plain_bytes = plain_hash.encode('utf-8')

    iv_bytes = bytes.fromhex(IV)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv_bytes)
    block_size = 16
    pad_len = block_size - (len(plain_bytes) % block_size)
    padded = plain_bytes + bytes([pad_len] * pad_len)
    encrypted = cipher.encrypt(padded)

    return base64.b64encode(encrypted).decode()


def calc_new_pwd256(old_pwd: str, new_pwd: str) -> str:
    """计算 newPwd256 (AES-CBC, SHA256 密钥派生) — newEncryptMode=1"""
    aes_key_hex = sha256_hex(old_pwd + KEY)[:32]
    aes_key = bytes.fromhex(aes_key_hex)
    plain_hash = sha256_hex(new_pwd + KEY)
    plain_bytes = plain_hash.encode('utf-8')

    iv_bytes = bytes.fromhex(IV)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv_bytes)
    block_size = 16
    pad_len = block_size - (len(plain_bytes) % block_size)
    padded = plain_bytes + bytes([pad_len] * pad_len)
    encrypted = cipher.encrypt(padded)

    return base64.b64encode(encrypted).decode()


def http_get(url: str, timeout: int = 10) -> dict:
    """HTTP GET 请求"""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body)


def http_post(url: str, data: dict, timeout: int = 10) -> dict:
    """HTTP POST 请求 (表单)"""
    post_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=post_data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body)


def auto_init(router_ip: str, ssid: str, wifi_pwd: str, admin_pwd: str) -> dict:
    """自动执行初始化流程，返回结果 dict"""
    base_url = f"http://{router_ip}"

    # Step 1: 登录 (newEncryptMode=1: 无需 nonce，明文密码 + init=1)
    login_url = (f"{base_url}/cgi-bin/luci/api/xqsystem/login"
                 f"?username=admin&logtype=2&password={FACTORY_PWD}&init=1")
    result = http_get(login_url)
    if result.get('code') != 0:
        return {"error": f"登录失败: {result}"}
    stok = result['token']

    # Step 2: 设置 WAN (DHCP) — POST 方式，带 autoset=1
    wan_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"
    result = http_post(wan_url, {"wanType": "dhcp", "autoset": "1"})
    if result.get('code') != 0:
        return {"error": f"设置WAN失败: {result}"}

    # Step 3: 设置 Wi-Fi + 管理密码
    nonce = generate_nonce()                          # 旧格式: 0__ts_rand
    old_pwd_hash = calc_old_pwd(nonce, FACTORY_PWD)  # SHA256
    new_pwd_enc = calc_new_pwd(FACTORY_PWD, admin_pwd)      # SHA1-AES (兼容)
    new_pwd256_enc = calc_new_pwd256(FACTORY_PWD, admin_pwd) # SHA256-AES

    post_data = {
        'ssid': ssid,
        'password': wifi_pwd,
        'name': ssid,
        'locale': '家',
        'encryption': 'mixed-psk',
        'txpwr': '1',
        'update': '1',
        'bw160': '1',
        'bsd': '1',
        'nonce': nonce,
        'oldPwd': old_pwd_hash,
        'newPwd': new_pwd_enc,
        'newPwd256': new_pwd256_enc,
        'routerPwd': admin_pwd,
    }
    set_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_router_normal"
    result = http_post(set_url, post_data, timeout=30)
    if result.get('code') != 0:
        return {"error": f"设置路由器失败: {result}"}

    return {
        "stok": stok,
        "ip": result.get('ip', router_ip),
        "ssid": ssid,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='小米 AX3000T 自动初始化向导（刷机前置）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 auto_init.py\n'
            '  python3 auto_init.py --ip 192.168.31.1 --ssid MyWiFi \\\n'
            '      --wifi-pwd 12345678 --admin-pwd 12345678\n'
        ))
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--ssid', default='Xiaomi_6ADF', help='Wi-Fi SSID (默认: Xiaomi_6ADF)')
    parser.add_argument('--wifi-pwd', default='12345678', help='Wi-Fi 密码 (默认: 12345678)')
    parser.add_argument('--admin-pwd', default='12345678', help='管理员密码 (默认: 12345678)')
    args = parser.parse_args()

    ret = auto_init(args.ip, args.ssid, args.wifi_pwd, args.admin_pwd)
    print(json.dumps(ret, ensure_ascii=False))
    if "error" in ret:
        sys.exit(1)
