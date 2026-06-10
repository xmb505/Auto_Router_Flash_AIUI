#!/usr/bin/env python3
"""登录路由器并获取 stok token（适配 AX3000T newEncryptMode=1）"""

import hashlib
import random
import time
import urllib.request
import urllib.parse
import json
import sys
import argparse

KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def nonce() -> str:
    ts = int(time.time())
    r = random.randint(0, 9999)
    return f"0__{ts}_{r}"


def login_pwd(nonce: str, admin_pwd: str) -> str:
    return sha256(nonce + sha256(admin_pwd + KEY))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='登录路由器并获取 stok')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--pwd', help='管理密码 (不传则交互输入)')
    args = parser.parse_args()

    pwd = args.pwd if args.pwd else input('管理密码: ')

    n = nonce()
    data = urllib.parse.urlencode({
        "username": "admin",
        "password": login_pwd(n, pwd),
        "logtype": "2",
        "nonce": n,
    }).encode()

    req = urllib.request.Request(f"http://{args.ip}/cgi-bin/luci/api/xqsystem/login", data=data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())

    if resp.get('code') == 0:
        print(json.dumps({"stok": resp['token']}))
    else:
        print(json.dumps({"error": resp.get('msg', '登录失败')}))
        sys.exit(1)
