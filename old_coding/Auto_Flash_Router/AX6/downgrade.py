#!/usr/bin/env python3
"""
AX6 固件降级脚本

上传指定固件文件到路由器并触发降级流程。
stok 需预先从 login_get_stok.py 获取，本脚本不自带登录。

用法:
    python3 downgrade.py --stok STOK --fw files/RA69_1.0.16.bin
"""

import json
import random
import sys
import urllib.request
import argparse


def http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def upload_firmware(ip: str, stok: str, fw_data: bytes) -> dict:
    """通过 multipart/form-data 上传固件"""
    boundary = b'----WebKitFormBoundary' + str(random.randint(100000, 999999)).encode()
    body = (
        b'--' + boundary + b'\r\n'
        b'Content-Disposition: form-data; name="image"; filename="firmware.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n' +
        fw_data +
        b'\r\n--' + boundary + b'--\r\n'
    )
    url = f"http://{ip}/uploadfile/cgi-bin/luci/;stok={stok}/api/xqsystem/upload_rom"
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary.decode())
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def downgrade(ip: str, stok: str, fw_path: str) -> dict:
    """执行完整降级流程"""
    # 读取固件
    try:
        with open(fw_path, 'rb') as f:
            fw_data = f.read()
    except FileNotFoundError:
        return {"error": f"文件未找到: {fw_path}"}

    print(json.dumps({"status": "uploading", "size": len(fw_data)}), file=sys.stderr)

    # Step 1: 上传固件
    r = upload_firmware(ip, stok, fw_data)
    if r.get('code') != 0:
        return {"error": f"上传固件失败: {r}"}
    print(json.dumps({"status": "upload_ok", "downgrade": r.get('downgrade')}), file=sys.stderr)

    # Step 2: 设置降级标志
    step2_url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
                 f"/web/syslock?flashtype=upload&downgrade=1")
    try:
        urllib.request.urlopen(step2_url, timeout=15)
    except Exception as e:
        return {"error": f"设置降级标志失败: {e}"}
    print(json.dumps({"status": "syslock_ok"}), file=sys.stderr)

    # Step 3: 确认刷入权限
    perm_url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
                f"/api/xqsystem/flash_permission")
    r = http_get(perm_url)
    if r.get('code') != 0:
        return {"error": f"刷机许可失败: {r}"}
    print(json.dumps({"status": "permission_ok"}), file=sys.stderr)

    # Step 4: 触发刷机（路由器将重启）
    flash_url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
                 f"/api/xqsystem/flash_rom?custom=1&recovery=1")
    r = http_get(flash_url, timeout=120)
    if r.get('code') != 0:
        return {"error": f"刷机请求失败: {r}"}
    print(json.dumps({"status": "flash_rom_ok"}), file=sys.stderr)

    return {
        "stok": stok,
        "downgrade": r.get('downgrade'),
        "firmware": fw_path,
        "size": len(fw_data),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='AX6 固件降级',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '示例:\n'
            '  python3 downgrade.py --stok STOK --fw files/RA69_1.0.16.bin\n'
        ))
    parser.add_argument('--stok', required=True, help='stok 令牌')
    parser.add_argument('--ip', default='192.168.31.1', help='路由器 IP (默认: 192.168.31.1)')
    parser.add_argument('--fw', required=True, help='固件文件路径')
    args = parser.parse_args()

    ret = downgrade(args.ip, args.stok, args.fw)
    print(json.dumps(ret, ensure_ascii=False))
    if "error" in ret:
        sys.exit(1)
