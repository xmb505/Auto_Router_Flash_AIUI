#!/usr/bin/env python3
# cr660x/7.firmware_upload_on_openwrt.py — scp 上传 sysupgrade 固件到 OpenWrt /tmp
#                                         + SSH sysupgrade -F 烧入持久 rootfs
#
# 适用机型: CR660X 系列 (MT7621A) — 适用于已启动到 initramfs OpenWrt 的阶段
# 前置:    6.openwrt_write_in_miwifi.py 已触发重启，路由器已进入 initramfs OpenWrt (192.168.1.1)
#          用户已有 squashfs-sysupgrade.bin（放在 files/ 下）
# 后置:    sysupgrade -F 执行 → 路由器自动重启进正式 OpenWrt（有持久 rootfs）
# 来源:    实机验证: sysupgrade -F /tmp/<file> → "Commencing upgrade. Closing all shell sessions."
#
# 输出:    stdout = 单个 JSON {"ok": bool, "step": ..., "data"|"error": ...}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import datetime
import json
import os
import subprocess
import sys

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.1.1"
DEFAULT_TIMEOUT = 120
DEFAULT_SSH_PWD = "admin"
STEP_NAME = "firmware_upload_on_openwrt"
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


# ============ SCP 上传 ============
def scp_upload(local_path: str, remote_name: str, ip: str, ssh_pwd: str,
               timeout: int) -> str:
    """scp 上传到 /tmp/<remote_name>，返回 remote_path。"""
    if not os.path.isfile(local_path):
        raise RuntimeError(f"文件不存在: {local_path}")

    remote_path = f"/tmp/{remote_name}"
    log(f"scp {local_path} → root@{ip}:{remote_path}")

    result = subprocess.run(
        [
            "sshpass", "-p", ssh_pwd,
            "scp", "-O",
            "-oStrictHostKeyChecking=no",
            "-oUserKnownHostsFile=/dev/null",
            local_path, f"root@{ip}:{remote_path}",
        ],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:300]
        raise RuntimeError(f"scp 上传失败 (exit={result.returncode}): {err}")

    log(f"上传完成: {remote_path}")
    return remote_path


# ============ SSH sysupgrade ============
def ssh_sysupgrade(ip: str, ssh_pwd: str, remote_path: str, timeout: int) -> None:
    """SSH 进路由器跑 sysupgrade -F，连接被远端关闭视为成功。"""
    cmd = f"sysupgrade -F {remote_path}"
    log(f"SSH root@{ip} {cmd}")

    result = subprocess.run(
        [
            "sshpass", "-p", ssh_pwd, "ssh",
            "-oStrictHostKeyChecking=no",
            "-oUserKnownHostsFile=/dev/null",
            "-oLogLevel=ERROR",
            f"root@{ip}", cmd,
        ],
        capture_output=True, text=True, timeout=timeout,
    )

    out = result.stdout.strip()
    err = result.stderr.strip()

    # sysupgrade -F 成功后路由器 reboot → 远端关闭连接 → ssh exit ≠ 0 (246)
    # "Commencing upgrade" 是唯一可信的成功标志（路由器开始升级流程后会关 SSH）
    # "Connection ... closed" 报文在 sshpass 侧可能被过滤，不依赖它
    if "Commencing upgrade" in out or "Commencing upgrade" in err:
        log("sysupgrade 已触发，路由器正在重启进正式 OpenWrt")
        return

    raise RuntimeError(
        f"sysupgrade 失败 (exit={result.returncode}): {out} {err}".strip()
    )


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CR660X 步骤 7：scp 上传 sysupgrade 固件 + SSH sysupgrade -F 烧入持久 rootfs（路由器自动重启）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 7.firmware_upload_on_openwrt.py --file files/immortalwrt-squashfs-sysupgrade.bin\n"
            "  python3 7.firmware_upload_on_openwrt.py --file files/immortalwrt-squashfs-sysupgrade.bin --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--file", required=True,
                   help="本地 squashfs-sysupgrade.bin 路径（scp 到 /tmp/ 后烧入）")
    p.add_argument("--target-name", default=None,
                   help="远程文件名（默认: 本地文件的 basename）")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help=f"SSH root 密码（默认: {DEFAULT_SSH_PWD}）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"操作超时秒（scp + sysupgrade，默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p.parse_args()


def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "CR660X 步骤 7：scp 上传 sysupgrade 固件 + sysupgrade -F 烧入持久 rootfs",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--file", "type": "file", "default": None,
             "required": True, "description": "本地 sysupgrade 固件路径"},
            {"name": "--target-name", "type": "string", "default": None,
             "required": False, "description": "远程文件名（默认 basename）"},
            {"name": "--ssh-pwd", "type": "string", "default": DEFAULT_SSH_PWD,
             "required": False, "description": "SSH root 密码"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "操作超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 7.firmware_upload_on_openwrt.py --file files/immortalwrt-squashfs-sysupgrade.bin",
        ],
        "stdin_contract": {"expects": None, "produces": "含 local_file/remote_file/action=upload+sysupgrade 的成功 JSON"},
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0

    args = parse_args()
    DEBUG = args.debug
    target = args.target_name or os.path.basename(args.file)

    try:
        remote = scp_upload(args.file, target, args.ip, args.ssh_pwd, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="file_not_found", recoverable=True)
        return 1

    try:
        ssh_sysupgrade(args.ip, args.ssh_pwd, remote, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="firmware_rejected", recoverable=True)
        return 1

    emit_ok({
        "local_file": args.file,
        "remote_file": remote,
        "ip": args.ip,
        "action": "upload + sysupgrade",
        "next_boot": "正式 OpenWrt（有持久 rootfs, 192.168.1.1）",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
