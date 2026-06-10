#!/usr/bin/env python3
"""
AX6 获取 5GHz WiFi 密码（= SSH 密码）
"""

import json
import sys
import urllib.request
import argparse


def http_get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_5g_password(data: dict) -> str:
    """从 wifi_detail_all 响应里挖 5GHz 密码"""
    info = data.get("info") or data.get("wifi")
    if isinstance(info, list):
        for item in info:
            # 5GHz 接口为 wl0 (IPQ807x 芯片组), SSID 通常包含 _5G
            if "_5G" in item.get("ssid", "") or item.get("ifname") == "wl0":
                if item.get("password"):
                    return item["password"]
    return ""


def main():
    parser = argparse.ArgumentParser(description="AX6 获取 5GHz WiFi 密码")
    parser.add_argument("--ip", default="192.168.31.1", help="AX6 IP (默认: 192.168.31.1)")
    parser.add_argument("--stok", required=True, help="stok 令牌")
    args = parser.parse_args()

    base = f"http://{args.ip}/cgi-bin/luci/;stok={args.stok}"
    url = f"{base}/api/xqnetwork/wifi_detail_all"
    r = http_get(url)
    if r.get("code") != 0:
        print(json.dumps({"error": f"API 失败: {r}"}))
        sys.exit(1)

    pwd = find_5g_password(r)
    if not pwd:
        print(json.dumps({"error": "未找到 5G 密码", "raw": r}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({"band": "5G", "password": pwd}, ensure_ascii=False))


if __name__ == "__main__":
    main()
