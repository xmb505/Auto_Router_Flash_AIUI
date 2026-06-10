#!/usr/bin/env python3
"""
小米 AX3600 路由器 自动初始化（刷机前置）脚本

适用机型:
    - 小米路由器 AX3600 (R3600)
    - 固件版本 1.1.19
    - newEncryptMode=0 (SHA1 旧版加密)

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
    """生成 nonce: 0__[timestamp]_[random]"""
    ts = int(time.time())
    rand = random.randint(0, 9999)
    return f"0__{ts}_{rand}"


def sha1_hex(s: str) -> str:
    """SHA1 hex 摘要"""
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def calc_login_password(nonce: str, old_pwd: str) -> str:
    """计算登录密码哈希: SHA1(nonce + SHA1(old_pwd + KEY))"""
    inner = sha1_hex(old_pwd + KEY)
    return sha1_hex(nonce + inner)


def calc_old_pwd(nonce: str, old_pwd: str) -> str:
    """与 login password 算法相同"""
    return calc_login_password(nonce, old_pwd)


def calc_new_pwd(old_pwd: str, new_pwd: str) -> str:
    """计算 newPwd (AES-CBC 加密)

    AES 密钥: SHA1(old_pwd + KEY) hex 取前 32 字符
    明文: SHA1(new_pwd + KEY) 的 hex 字符串 (UTF-8 编码)
    """
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


def get_firmware_version(router_ip: str) -> str:
    """获取固件版本号"""
    try:
        r = http_get(f"http://{router_ip}/cgi-bin/luci/api/xqsystem/init_info")
        return r.get('romversion', '')
    except Exception:
        return ''


def need_bw160(version: str) -> bool:
    """是否需要 bw160 字段（新固件 >= 1.1.x 需要）"""
    try:
        parts = version.split('.')
        major, minor = int(parts[0]), int(parts[1])
        return major >= 1 and minor >= 1
    except (ValueError, IndexError):
        # 不确定版本时保守处理，添加 bw160
        return True


def auto_init(router_ip: str, ssid: str, wifi_pwd: str, admin_pwd: str) -> dict:
    """自动执行初始化流程，返回结果 dict"""
    base_url = f"http://{router_ip}"

    # Step 0: 检测固件版本
    fw_ver = get_firmware_version(router_ip)
    has_bw160 = need_bw160(fw_ver)
    print(json.dumps({"status": f"固件版本 {fw_ver}, bw160={has_bw160}"}), file=sys.stderr)

    # Step 1: 登录 (newEncryptMode=0: SHA1 双哈希)
    login_nonce = generate_nonce()
    login_pwd = calc_login_password(login_nonce, FACTORY_PWD)
    login_url = (f"{base_url}/cgi-bin/luci/api/xqsystem/login"
                 f"?username=admin&logtype=2&nonce={login_nonce}"
                 f"&password={login_pwd}&init=1&privacy=1")
    result = http_get(login_url)
    if result.get('code') != 0:
        return {"error": f"登录失败: {result}"}
    stok = result['token']

    # Step 2: 设置 WAN (DHCP) — POST 方式 (newEncryptMode=0)
    wan_url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"
    result = http_post(wan_url, {"wanType": "dhcp", "autoset": "0"})
    if result.get('code') != 0:
        return {"error": f"设置WAN失败: {result}"}

    # Step 3: 禁用自动更新
    upgrade_url = (f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/vas_switch"
                   f"?info=auto_upgrade%3D0")
    result = http_get(upgrade_url)
    if result.get('code') != 0:
        return {"error": f"禁用自动更新失败: {result}"}

    # Step 4: 设置 Wi-Fi + 管理密码
    set_nonce = generate_nonce()
    old_pwd_hash = calc_old_pwd(set_nonce, FACTORY_PWD)
    new_pwd_hash = calc_new_pwd(FACTORY_PWD, admin_pwd)

    post_data = {
        'name': ssid,
        'locale': '家',
        'ssid': ssid,
        'password': wifi_pwd,
        'encryption': 'mixed-psk',
        'nonce': set_nonce,
        'newPwd': new_pwd_hash,
        'oldPwd': old_pwd_hash,
        'txpwr': '1',
        'routerPwd': admin_pwd,
    }
    if has_bw160:
        post_data['bw160'] = 'false'
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
        description='小米 AX3600 自动初始化向导（刷机前置）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 auto_init.py\n'
            '  python3 auto_init.py --ip 192.168.31.1 --ssid XiaoMI_G74C \\\n'
            '      --wifi-pwd 12345678 --admin-pwd 12345678\n'
        ))
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--ssid', default='Xiaomi_20A4', help='Wi-Fi SSID (默认: Xiaomi_20A4)')
    parser.add_argument('--wifi-pwd', default='12345678', help='Wi-Fi 密码 (默认: 12345678)')
    parser.add_argument('--admin-pwd', default='12345678', help='管理员密码 (默认: 12345678)')
    args = parser.parse_args()

    ret = auto_init(args.ip, args.ssid, args.wifi_pwd, args.admin_pwd)
    print(json.dumps(ret, ensure_ascii=False))
    if "error" in ret:
        sys.exit(1)
