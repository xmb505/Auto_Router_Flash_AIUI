#!/usr/bin/env python3
"""上传固件并降级路由器"""

import json
import sys
import urllib.request
import hashlib
import random
import time
import argparse

KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"


def http_post_raw(url: str, data: bytes):
    """模拟浏览器 multipart/form-data 上传固件"""
    boundary = b'----WebKitFormBoundary' + str(random.randint(100000, 999999)).encode()
    body = (
        b'--' + boundary + b'\r\n'
        b'Content-Disposition: form-data; name="image"; filename="firmware.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n' +
        data +
        b'\r\n--' + boundary + b'--\r\n'
    )
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary.decode())
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def http_get(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='上传固件并降级路由器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 downgrade.py --stok xxx --fw files/RA67_1.0.26.bin\n'
            '  python3 downgrade.py --ip 192.168.31.1 --pwd 12345678 --fw files/RA67_1.0.26.bin\n'
        ))
    parser.add_argument('--stok', help='已登录的 stok')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--pwd', help='管理密码 (不传 --stok 时使用)')
    parser.add_argument('--fw', required=True, help='固件文件路径')
    args = parser.parse_args()

    ip = args.ip
    stok = args.stok
    fw_path = args.fw

    if not stok:
        if not args.pwd:
            args.pwd = input('管理密码: ')
        stok = login(ip, args.pwd)
    else:
        if args.pwd:
            print(json.dumps({"error": "同时指定了 --stok 和 --pwd，请只用一种方式"}))
            sys.exit(1)

    # 读取固件
    try:
        with open(fw_path, 'rb') as f:
            fw_data = f.read()
    except FileNotFoundError:
        print(json.dumps({"error": f"文件未找到: {fw_path}"}))
        sys.exit(1)

    print(json.dumps({"status": "uploading", "size": len(fw_data)}), file=sys.stderr)

    # Step 1: 上传固件
    url = f"http://{ip}/uploadfile/cgi-bin/luci/;stok={stok}/api/xqsystem/upload_rom"
    try:
        r = http_post_raw(url, fw_data)
    except Exception as e:
        print(json.dumps({"error": f"上传失败: {e}"}))
        sys.exit(1)

    if r.get('code') != 0:
        print(json.dumps({"error": f"上传固件失败: {r}"}))
        sys.exit(1)

    downgrade = r.get('downgrade', False)

    # Step 2: 刷入（清除用户配置）
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/xqsystem/flash_rom?custom=1&recovery=1"
    try:
        r = http_get(url)
    except Exception as e:
        print(json.dumps({"error": f"刷机请求失败: {e}"}))
        sys.exit(1)

    if r.get('code') != 0:
        print(json.dumps({"error": f"刷机失败: {r}"}))
        sys.exit(1)

    print(json.dumps({
        "stok": stok,
        "downgrade": downgrade,
        "firmware": fw_path,
    }))
