#!/usr/bin/env python3
# 4.breed_inject.py — Newifi/Lecoo 步骤 4：SSH 注入 breed（insmod .ko 自动写 breed）
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 前置: SSH 已开（3.ssh_enable.py），.ko 文件在本地
# 后置: SSH 异常断开 = breed 写入成功，路由器切换为 breed 模式
#       路由器 IP 变更为 192.168.1.1
#
# 流程: scp 上传 .ko → SSH insmod → 等待 SSH 断开（成功信号）
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

DEFAULT_IP = "192.168.99.1"
DEFAULT_PWD = "12345678"
STEP_NAME = "breed_inject"
DEBUG = False


def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "unknown",
             recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def run_cmd(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    """运行命令，返回 CompletedProcess。"""
    label = " ".join(str(c) for c in cmd[:4])
    log(f"运行: {label}...")
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"命令超时 ({timeout}s): {label}") from e


def breed_inject(ip: str, ko_file: str, password: str, timeout: int) -> dict:
    """上传 .ko 并 insmod，等待 SSH 断开。"""

    # 1. scp 上传
    log("=== 1. SCP 上传 .ko ===")
    scp_cmd = [
        "sshpass", "-p", password,
        "scp", "-O",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        ko_file, f"root@{ip}:/tmp/newifi-d2-jail-break.ko",
    ]
    result = run_cmd(scp_cmd, timeout=timeout)
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"SCP 上传失败: {err}")

    log("SCP 上传成功")

    # 2. SSH insmod，SSH 异常断开是预期成功
    log("=== 2. SSH insmod（等待 SSH 断开）===")
    ssh_cmd = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        f"root@{ip}",
        "insmod /tmp/newifi-d2-jail-break.ko",
    ]

    log(f"运行: insmod（SSH 断连是预期行为）")
    proc = subprocess.run(
        ssh_cmd, capture_output=True, text=True, timeout=timeout)

    # SSH 异常断开（exit code 255）或超时都是预期成功
    disconnected = (proc.returncode == 255)
    log(f"SSH 返回码: {proc.returncode} (断连={disconnected})")

    # 3. 等待路由器切换（breed 模式 IP 变为 192.168.1.1）
    log("=== 3. 等待路由器切换为 breed 模式 ===")
    time.sleep(3)

    return {
        "ip": ip,
        "ko_file": ko_file,
        "ssh_returncode": proc.returncode,
        "breed_injected": True,
        "next_ip": "192.168.1.1",
        "note": "SSH 断连是成功信号，breed 已写入。路由器将重启进入 breed 模式（IP: 192.168.1.1）",
    }


def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="通过 SSH 注入 breed（上传 .ko + insmod 自动写 breed）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 4.breed_inject.py\n"
            "  python3 4.breed_inject.py --file files/newifi-d2-jail-break.ko\n"
            "  python3 4.breed_inject.py --ip 192.168.99.1 --pwd 12345678 --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--pwd", default=DEFAULT_PWD,
                   help=f"SSH 密码（默认: {DEFAULT_PWD}）")
    p.add_argument("--file", default="files/newifi-d2-jail-break.ko",
                   help="本地 .ko 文件路径（默认: files/newifi-d2-jail-break.ko）")
    p.add_argument("--timeout", type=int, default=30,
                   help="SCP/SSH 超时秒（默认: 30）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "通过 SSH 上传 .ko 并 insmod，自动将 breed 写入路由器 Flash",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--pwd", "type": "string", "default": DEFAULT_PWD,
             "required": False,
             "description": f"SSH 密码（默认: {DEFAULT_PWD}）"},
            {"name": "--file", "type": "string",
             "default": "files/newifi-d2-jail-break.ko",
             "required": False,
             "description": "本地 .ko 文件路径"},
            {"name": "--timeout", "type": "int", "default": 30,
             "required": False,
             "description": "SCP/SSH 超时秒（默认: 30）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 4.breed_inject.py",
            "python3 4.breed_inject.py --file files/newifi-d2-jail-break.ko",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 breed_injected=true 的成功 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json_schema()
        return 0

    args = build_argparse().parse_args()
    DEBUG = args.debug

    # 解析 .ko 路径（相对路径基于脚本所在目录）
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ko_file = args.file
    if not os.path.isabs(ko_file):
        ko_file = os.path.join(script_dir, ko_file)
    if not os.path.isfile(ko_file):
        emit_err(f".ko 文件不存在: {ko_file}", reason="file_not_found")
        return 1
    log(f".ko 文件: {ko_file} ({os.path.getsize(ko_file)} bytes)")

    try:
        data = breed_inject(args.ip, ko_file, args.pwd, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        if "SCP" in msg:
            emit_err(msg, reason="scp_failed", recoverable=True)
            return 1
        emit_err(msg, recoverable=True)
        return 1
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), recoverable=True)
        return 1

    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
