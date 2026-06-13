#!/usr/bin/env python3
# cr660x/5.uboot_write_in_miwifi.py — SSH 进 miwifi，mtd write pb-boot 到 Bootloader
#
# 适用机型: CR660X 系列 (MT7621A)
# 前置:    3.enable_ssh.py 已启用 SSH + 4.firmware_upload_on_miwifi.sh 已传 pb-boot.img 到 /tmp/
# 后置:    pb-boot 写入 mtd0（PandoraBox 第三方 uboot），**不重启**
# 来源:    实机验证 — mtd unlock /dev/mtd0 && mtd write /tmp/pb-boot.img /dev/mtd0
#
# 输出:    stdout = 单个 JSON {"ok": bool, "step": ..., "data"|"error":..., "reason"?}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import datetime
import json
import os
import subprocess
import sys

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
STEP_NAME = "uboot_write_in_miwifi"
DEBUG = False

# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


# ============ miwifi_ssh 封装 ============
def miwifi_ssh_cmd(ip: str, ssh_pwd: str, command: str, timeout: int) -> dict:
    """调用同目录 miwifi_ssh.sh 跑单条命令，返回解析后的 JSON 对象。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ssh_script = os.path.join(script_dir, "miwifi_ssh.sh")
    result = subprocess.run(
        [ssh_script, "--ip", ip, "--pwd", ssh_pwd, "--cmd", command],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f"miwifi_ssh.sh 失败 (exit={result.returncode}): {result.stderr.strip()}")
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("miwifi_ssh.sh 无输出")
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        arr = json.loads(raw, strict=False)
    if not arr:
        raise RuntimeError("miwifi_ssh.sh 返回空数组")
    return arr[0]


# ============ 主流程 ============
def uboot_write(ip: str, ssh_pwd: str, remote_file: str, timeout: int) -> dict:
    target_path = f"/tmp/{remote_file}"

    # 1. 解锁 mtd0
    log("解锁 /dev/mtd0...")
    unlock = miwifi_ssh_cmd(ip, ssh_pwd, "mtd unlock /dev/mtd0", timeout)
    if not unlock.get("ok"):
        raise RuntimeError(f"mtd unlock 失败: {unlock.get('stderr', unlock.get('stdout', ''))}")

    # 2. 写 pb-boot
    log(f"mtd write {target_path} → /dev/mtd0 ...")
    write = miwifi_ssh_cmd(ip, ssh_pwd, f"mtd write {target_path} /dev/mtd0", timeout)
    if not write.get("ok"):
        raise RuntimeError(f"mtd write 失败: {write.get('stderr', write.get('stdout', ''))}")
    stdout = write.get("stdout", "")
    if "Writing from" not in stdout and "Writing from" not in write.get("stderr", ""):
        raise RuntimeError(f"mtd write 输出异常: {stdout}")

    log("pb-boot 已写入 mtd0（未重启）")
    return {
        "ip": ip,
        "remote_file": target_path,
        "mtd": "/dev/mtd0",
        "rebooted": False,
    }


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CR660X 步骤 5：SSH 进 miwifi，mtd write pb-boot 到 Bootloader（不重启）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 5.uboot_write_in_miwifi.py --file pb-boot.img\n"
            "  python3 5.uboot_write_in_miwifi.py --file pb-boot.img --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--file", required=True,
                   help="路由器 /tmp/ 下的文件名（由 4.firmware_upload_on_miwifi.sh 上传）")
    p.add_argument("--ssh-pwd", default="root",
                   help="SSH root 密码（默认: root）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"SSH 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p.parse_args()


def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "CR660X 步骤 5：SSH 进 miwifi，mtd write pb-boot 到 Bootloader（不重启）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--file", "type": "string", "default": None,
             "required": True, "description": "路由器 /tmp/ 下的文件名"},
            {"name": "--ssh-pwd", "type": "string", "default": "root",
             "required": False, "description": "SSH root 密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "SSH 超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 5.uboot_write_in_miwifi.py --file pb-boot.img",
        ],
        "stdin_contract": {"expects": None, "produces": "含 mtd 写入结果的成功 JSON"},
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0

    args = parse_args()
    DEBUG = args.debug

    try:
        data = uboot_write(args.ip, args.ssh_pwd, args.file, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="mtd_write_failed", recoverable=True)
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
