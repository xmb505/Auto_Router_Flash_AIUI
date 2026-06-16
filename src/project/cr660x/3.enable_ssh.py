#!/usr/bin/env python3
# cr660x/3.enable_ssh.py — extendwifi + oneclick 启用 SSH (通杀)
# 前置: 路由器已初始化 + 一个有效 stok (步骤 2 输出)
# 后置: 路由器 SSH 端口 22 可连
# 来源: old_coding/haku-cr660x-sidehackwifi/刷机/test_login.sh (2026-03-28)

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_IP = "192.168.31.1"
TIMEOUT = 60
SSH_PROBE_RETRIES = 11
SSH_PROBE_INTERVAL = 3
STEP_NAME = "enable_ssh"
DEBUG = False


def log(msg):
    if DEBUG:
        print(f"[{STEP_NAME}] {msg}", file=sys.stderr)


def emit_ok(data):
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error, reason=""):
    out = {"ok": False, "step": STEP_NAME, "error": error, "recoverable": True}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def http_get(url, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"HTTP GET 失败: {e}") from e


def http_get_raw(url, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"HTTP GET 失败: {e}") from e


def call_extendwifi_connect(stok, ip, ssid, password, timeout):
    qs = urllib.parse.urlencode({"ssid": ssid, "password": password})
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/misystem/extendwifi_connect?{qs}"
    log(f"extendwifi_connect ssid={ssid!r}")
    try:
        data = http_get(url, timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"extendwifi_connect HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
    msg = (data.get("msg") or "").lower()
    if "connect succces" not in msg:
        raise RuntimeError(f"extendwifi_connect 失败: code={data.get('code')} msg={data.get('msg')!r}")


def call_oneclick_get_remote_token(stok, ip, timeout):
    qs = urllib.parse.urlencode({"username": "xxx", "password": "xxx", "nonce": "xxx"})
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/xqsystem/oneclick_get_remote_token?{qs}"
    log("oneclick_get_remote_token")
    try:
        text = http_get_raw(url, timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"oneclick_get_remote_token HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
    if "nvram" not in text.lower():
        raise RuntimeError(f"oneclick_get_remote_token 响应无 'nvram': {text[:200]}")


def probe_ssh_port(host, port=22, timeout=5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def read_stok_from_stdin():
    if sys.stdin.isatty():
        raise RuntimeError("未传 --stok, stdin 也不是管道")
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("stdin 为空")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"stdin 不是合法 JSON: {e}")
    if d.get("ok") is False:
        raise RuntimeError(f"上游失败: {d.get('error', '未知')}")
    stok = d.get("data", {}).get("stok", "")
    if not stok:
        raise RuntimeError("上游 JSON 没有 data.stok")
    return stok


def main():
    global DEBUG
    if "--help-json" in sys.argv:
        schema = {
            "script": STEP_NAME,
            "description": "CR660X 步骤 3: extendwifi+oneclick 启用 SSH",
            "args": [
                {"name": "--ip", "default": DEFAULT_IP, "required": False},
                {"name": "--stok", "default": "", "required": False,
                 "description": "stok (空则从 stdin 读)"},
                {"name": "--extendwifi-ssid", "default": "socket.gethostname()", "required": False,
                 "description": "占位 SSID (路由器不真连)"},
                {"name": "--extendwifi-password", "default": "12345678", "required": False},
                {"name": "--timeout", "default": TIMEOUT, "required": False},
                {"name": "--debug", "default": False, "required": False},
            ],
            "examples": [
                "python3 3.enable_ssh.py --stok <stok>",
                "python3 2.login_get_stok.py --pwd mypass | python3 3.enable_ssh.py",
            ],
            "stdin_contract": {"expects": "上游 JSON (含 data.stok)", "produces": "含 ssh_port 的成功 JSON"},
        }
        print(json.dumps(schema, ensure_ascii=False, indent=2))
        return 0

    p = argparse.ArgumentParser(description="CR660X 步骤 3: 启用 SSH (extendwifi+oneclick)")
    p.add_argument("--ip", default=DEFAULT_IP)
    p.add_argument("--stok", default="")
    p.add_argument("--extendwifi-ssid", default=socket.gethostname())
    p.add_argument("--extendwifi-password", default="12345678")
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    DEBUG = args.debug

    try:
        stok = args.stok or read_stok_from_stdin()
    except RuntimeError as e:
        emit_err(str(e), reason="stok_missing")
        return 1

    try:
        call_extendwifi_connect(stok, args.ip, args.extendwifi_ssid, args.extendwifi_password, args.timeout)
        call_oneclick_get_remote_token(stok, args.ip, args.timeout)
    except RuntimeError as e:
        emit_err(str(e), reason="ssh_failed")
        return 1

    log(f"探测 TCP {args.ip}:22 (最多 {SSH_PROBE_RETRIES}x{SSH_PROBE_INTERVAL}s)...")
    for i in range(SSH_PROBE_RETRIES):
        if probe_ssh_port(args.ip):
            emit_ok({"ip": args.ip, "ssh_port": 22})
            return 0
        if i < SSH_PROBE_RETRIES - 1:
            time.sleep(SSH_PROBE_INTERVAL)
    emit_err(f"SSH 端口 22 在 {SSH_PROBE_RETRIES * SSH_PROBE_INTERVAL}s 内未打开", reason="ssh_failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
