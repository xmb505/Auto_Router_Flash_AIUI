#!/usr/bin/env python3
# AX3000T 步骤 5：从 initramfs sysupgrade 到完整 OpenWrt
#
# 适用机型: 小米路由器 AX3000T (RD03) — MediaTek Filogic 820 (MT7981)
# 前置:    initramfs 系统已启动，SSH 可达 192.168.1.1
# 后置:    路由器重启进入完整 OpenWrt/ImmortalWrt（持久 rootfs）
# 默认 SSH: root 空密码（ImmortalWrt initramfs 默认）
#
# 流程:
#   1. SCP 上传 sysupgrade .itb 到 /tmp/
#   2. SSH 执行 sysupgrade -n /tmp/<file>（-n = 不保留配置）
#   3. 路由器自动重启到完整 OpenWrt
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ============ 常量 ============
DEFAULT_IP = "192.168.1.1"           # OpenWrt/initramfs 默认 IP
DEFAULT_SSH_PWD = ""                  # ImmortalWrt initramfs 默认空密码
DEFAULT_TIMEOUT = 120
STEP_NAME = "sysupgrade_openwrt"
DEBUG = False
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认 sysupgrade 文件
DEFAULT_SYSUPGRADE_FILE = os.path.join(
    SCRIPT_DIR, "files",
    "immortalwrt-mediatek-filogic-xiaomi_mi-router-ax3000t-ubootmod-squashfs-sysupgrade.itb"
)


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


# ============ SSH/SCP 工具 ============
def _ssh_base(ssh_pwd: str) -> list:
    """构建 sshpass + ssh 基础命令（OpenWrt 用 ED25519 host key，无需 +ssh-rsa）"""
    base = ["sshpass", "-p", ssh_pwd, "ssh",
            "-oHostKeyAlgorithms=+ssh-rsa",
            "-oStrictHostKeyChecking=no",
            "-oUserKnownHostsFile=/dev/null",
            "-oLogLevel=ERROR"]
    return base


def ssh_cmd(ip: str, ssh_pwd: str, cmd: str, timeout: int) -> tuple:
    """sshpass + ssh 跑一条命令; 返回 (ok, stdout, stderr)"""
    log(f"ssh root@{ip}: {cmd[:80]}{'...' if len(cmd) > 80 else ''}")
    proc = subprocess.run(
        _ssh_base(ssh_pwd) + [f"root@{ip}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def scp_upload(local_path: str, remote_path: str, ip: str, ssh_pwd: str,
               timeout: int) -> tuple:
    """scp 上传文件; 返回 (ok, error_msg)"""
    log(f"scp {local_path} → root@{ip}:{remote_path}")
    proc = subprocess.run([
        "sshpass", "-p", ssh_pwd,
        "scp", "-O",
        "-oHostKeyAlgorithms=+ssh-rsa",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        "-oLogLevel=ERROR",
        local_path, f"root@{ip}:{remote_path}",
    ], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, ""


def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_openwrt_boot(ip: str, timeout: int = 180) -> bool:
    """等待完整 OpenWrt 系统上线"""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((ip, 22), timeout=3):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(5)
    return False


# ============ 主流程 ============
def sysupgrade(ip: str, ssh_pwd: str, fw_path: str, timeout: int) -> dict:
    # 0. 验证本地文件
    if not os.path.isfile(fw_path):
        raise RuntimeError(f"sysupgrade 文件不存在: {fw_path}")
    local_md5 = file_md5(fw_path)
    file_size = os.path.getsize(fw_path)
    fw_name = os.path.basename(fw_path)
    log(f"sysupgrade 文件: {fw_path} ({file_size} bytes, MD5={local_md5})")

    remote_path = f"/tmp/{fw_name}"

    # 1. SCP 上传
    log("Step 1/3: SCP 上传 sysupgrade 固件")
    ok, err = scp_upload(fw_path, remote_path, ip, ssh_pwd, timeout)
    if not ok:
        raise RuntimeError(f"SCP 上传失败: {err}")
    log("上传完成")

    # 2. SSH 验证 MD5
    log("Step 2/3: 验证远程 MD5")
    ok, stdout, stderr = ssh_cmd(
        ip, ssh_pwd,
        f"md5sum {remote_path} | cut -d' ' -f1",
        timeout=30,
    )
    if ok:
        remote_md5 = stdout.strip()
        if local_md5 != remote_md5:
            raise RuntimeError(
                f"MD5 不匹配! 本地={local_md5} 远程={remote_md5}"
            )
        log(f"MD5 匹配: {local_md5}")
    else:
        log(f"MD5 校验跳过（initramfs 可能无 md5sum）: {stderr}", level="WARN")

    # 3. SSH sysupgrade
    log("Step 3/3: sysupgrade -n（不保留配置）")
    try:
        ssh_cmd(ip, ssh_pwd, f"sysupgrade -n {remote_path}", timeout=60)
    except subprocess.TimeoutExpired:
        log("sysupgrade 已发出（连接中断，符合预期）")

    # 4. 等待 OpenWrt 重启完成
    log("等待 OpenWrt 重启...")
    booted = wait_openwrt_boot(ip, timeout=180)
    if booted:
        log("OpenWrt 已上线")
    else:
        log("OpenWrt 未在 180s 内上线（可能需要更多时间）", level="WARN")

    return {
        "ip": ip,
        "firmware": fw_path,
        "file_size": file_size,
        "md5": local_md5,
        "sysupgrade_args": "-n",
        "reboot": True,
        "openwrt_ready": booted,
    }


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "sysupgrade_openwrt",
        "description": "AX3000T 步骤 5：从 initramfs sysupgrade 到完整 OpenWrt",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False, "description": "initramfs 系统 IP"},
            {"name": "--ssh-pwd", "type": "string", "default": DEFAULT_SSH_PWD,
             "required": False, "description": "SSH 密码（ImmortalWrt initramfs 默认空）"},
            {"name": "--file", "type": "string", "default": "",
             "required": False, "description": "sysupgrade .itb 文件路径"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 5.sysupgrade_openwrt.py",
            "python3 5.sysupgrade_openwrt.py --file files/immortalwrt-...-sysupgrade.itb --debug",
        ],
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3000T 步骤 5：从 initramfs sysupgrade 到完整 OpenWrt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 5.sysupgrade_openwrt.py\n"
            "  python3 5.sysupgrade_openwrt.py --file files/immortalwrt-...-sysupgrade.itb --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"initramfs 系统 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help="SSH 密码（默认: 空，ImmortalWrt initramfs 默认免密）")
    p.add_argument("--file", default="",
                   help="sysupgrade .itb 文件路径（默认 files/ 下的 sysupgrade.itb）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug

    fw_path = args.file or DEFAULT_SYSUPGRADE_FILE
    try:
        data = sysupgrade(args.ip, args.ssh_pwd, fw_path, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
