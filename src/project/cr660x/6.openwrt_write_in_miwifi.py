#!/usr/bin/env python3
# cr660x/6.openwrt_write_in_miwifi.py — SSH 进 miwifi，sysupgrade -F 烧 initramfs
#
# 适用机型: CR660X 系列 (MT7621A)
# 前置:    3.enable_ssh.py 已启用 SSH + 4.firmware_upload_on_miwifi.sh 已传 initramfs 到 /tmp/
#          + 5.uboot_write_in_miwifi.py 已写 pb-boot（否则重启起不来）
# 后置:    路由器自动重启进 initramfs OpenWrt（192.168.1.1），**无持久 rootfs**
# 来源:    实机验证 — sysupgrade -F /tmp/initramfs-kernel.bin
#          输出: Commencing upgrade. Closing all shell sessions.
#                Connection to 192.168.31.1 closed by remote host.
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
DEFAULT_TIMEOUT = 60
STEP_NAME = "openwrt_write_in_miwifi"
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


# ============ SSH 直连（不走 miwifi_ssh.sh——sysupgrade 会导致连接被远端关闭） ============
def ssh_sysupgrade(ip: str, ssh_pwd: str, remote_file: str, timeout: int) -> dict:
    """SSH 进路由器跑 sysupgrade -F，连接被远端关闭视为成功。"""
    target_path = f"/tmp/{remote_file}"
    cmd = f"sysupgrade -F {target_path}"

    log(f"SSH root@{ip} sysupgrade -F {target_path}")

    result = subprocess.run(
        [
            "sshpass", "-p", ssh_pwd, "ssh",
            "-oHostKeyAlgorithms=+ssh-rsa",
            "-oStrictHostKeyChecking=no",
            "-oUserKnownHostsFile=/dev/null",
            "-oLogLevel=ERROR",
            f"root@{ip}", cmd,
        ],
        capture_output=True, text=True, timeout=timeout,
    )

    out = result.stdout.strip()
    err = result.stderr.strip()
    combined = f"{out}\n{err}"

    # sysupgrade -F 成功后路由器 reboot → 远端关闭连接 → ssh exit ≠ 0
    # 成功标志：输出含 "Commencing upgrade" + "Connection.*closed"
    is_sysupgrade_ok = (
        "Commencing upgrade" in combined
        and ("closed by remote host" in combined or "Connection to" in combined)
    )

    if is_sysupgrade_ok:
        log("sysupgrade 已触发，路由器正在重启进 initramfs OpenWrt")
        return {
            "ip": ip,
            "remote_file": target_path,
            "action": "sysupgrade -F initramfs",
            "next_boot": "initramfs OpenWrt (192.168.1.1, 无持久 rootfs)",
        }

    # 不是预期输出 → 真失败
    raise RuntimeError(
        f"sysupgrade 失败 (exit={result.returncode}): {out} {err}".strip()
    )


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CR660X 步骤 6：SSH 进 miwifi，sysupgrade -F 烧 initramfs（路由器自动重启）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 6.openwrt_write_in_miwifi.py --file initramfs-kernel.bin\n"
            "  python3 6.openwrt_write_in_miwifi.py --file initramfs-kernel.bin --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--file", required=True,
                   help="路由器 /tmp/ 下的 initramfs 文件名（由 4.firmware_upload_on_miwifi.sh 上传）")
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
        "description": "CR660X 步骤 6：SSH 进 miwifi，sysupgrade -F 烧 initramfs（路由器自动重启）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--file", "type": "string", "default": None,
             "required": True, "description": "路由器 /tmp/ 下的 initramfs 文件名"},
            {"name": "--ssh-pwd", "type": "string", "default": "root",
             "required": False, "description": "SSH root 密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "SSH 超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 6.openwrt_write_in_miwifi.py --file initramfs-kernel.bin",
        ],
        "stdin_contract": {"expects": None, "produces": "含 sysupgrade 结果的成功 JSON"},
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
        data = ssh_sysupgrade(args.ip, args.ssh_pwd, args.file, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="firmware_rejected", recoverable=True)
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
