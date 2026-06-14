#!/usr/bin/env python3
# AX3000T 步骤 4：刷自定义 uboot (FIP) 到 FIP 分区 (mtd5)
#
# 适用机型: 小米路由器 AX3000T (RD03) — MediaTek Filogic 820 (MT7981)
# MTD 布局: mtd5 = FIP (uboot FIT image)，2MB
# 前置:    SSH 已开启（步骤 4），root@192.168.31.1 密码 root
# 后置:    FIP 已替换为自定义 uboot，reboot 后 uboot 自动 TFTP 拉取 recovery
# 来源:    old_coding/Auto_Flash_Router/AX3000T/flash_uboot.sh
#
# ⚠️ 这是 AX3000T 独有步骤，AX5/AX6 不需要。
#    AX3000T 的刷机流程是: 替换 FIP → uboot TFTP recovery 拉 initramfs → sysupgrade
#    而非 AX5/AX6 的 ubiformat 直刷 rootfs mtd。
#
# 流程:
#   1. SCP 上传 .fip 文件到 /tmp/uboot.fip
#   2. SSH 验证 MD5 一致性（安全措施）
#   3. SSH 执行 mtd write /tmp/uboot.fip FIP && sync
#   4. SSH reboot（路由器重启后由自定义 uboot 接管）
#   5. 自定义 uboot 引导系统，可从 initramfs 做 sysupgrade（步骤 5）
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
from datetime import datetime, timezone

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # stock 固件 IP
DEFAULT_SSH_PWD = "root"
DEFAULT_TIMEOUT = 60
STEP_NAME = "flash_uboot"
DEBUG = False
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认 uboot 文件
DEFAULT_UBOOT_FILE = os.path.join(
    SCRIPT_DIR, "files",
    "immortalwrt-25.12.0-mediatek-filogic-xiaomi_mi-router-ax3000t-ubootmod-bl31-uboot.fip"
)

# MTD 目标 (FIP 分区)
TARGET_MTD = "FIP"


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
def ssh_cmd(ip: str, ssh_pwd: str, cmd: str, timeout: int) -> tuple:
    """sshpass + ssh 跑一条命令; 返回 (ok, stdout, stderr)"""
    log(f"ssh root@{ip}: {cmd[:80]}{'...' if len(cmd) > 80 else ''}")
    proc = subprocess.run([
        "sshpass", "-p", ssh_pwd,
        "ssh",
        "-oHostKeyAlgorithms=+ssh-rsa",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        "-oLogLevel=ERROR",
        f"root@{ip}", cmd,
    ], capture_output=True, text=True, timeout=timeout)
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
    """计算本地文件 MD5"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ============ 主流程 ============
def flash_uboot(router_ip: str, ssh_pwd: str, uboot_file: str,
                  timeout: int) -> dict:
    # 0. 验证本地文件
    if not os.path.isfile(uboot_file):
        raise RuntimeError(f"uboot 文件不存在: {uboot_file}")
    local_md5 = file_md5(uboot_file)
    file_size = os.path.getsize(uboot_file)
    log(f"uboot 文件: {uboot_file} ({file_size} bytes, MD5={local_md5})")

    remote_path = "/tmp/uboot.fip"

    # 1. SCP 上传
    log("Step 1/4: SCP 上传 uboot.fip")
    ok, err = scp_upload(uboot_file, remote_path, router_ip, ssh_pwd, timeout)
    if not ok:
        raise RuntimeError(f"SCP 上传失败: {err}")
    log("上传完成")

    # 2. SSH 验证 MD5
    log("Step 2/4: 验证远程 MD5")
    ok, stdout, stderr = ssh_cmd(
        router_ip, ssh_pwd,
        f"md5sum {remote_path} | cut -d' ' -f1",
        timeout=30,
    )
    if not ok:
        raise RuntimeError(f"MD5 校验失败: {stderr}")
    remote_md5 = stdout.strip()
    if local_md5 != remote_md5:
        raise RuntimeError(
            f"MD5 不匹配! 本地={local_md5} 远程={remote_md5}。"
            f"请重新上传。"
        )
    log(f"MD5 匹配: {local_md5}")

    # 3. SSH mtd write (用分区名 FIP 而非设备名 /dev/mtd5)
    log(f"Step 3/4: mtd write {TARGET_MTD}")
    ok, stdout, stderr = ssh_cmd(
        router_ip, ssh_pwd,
        f"mtd write {remote_path} {TARGET_MTD} && sync && echo OK",
        timeout=60,
    )
    if not ok:
        raise RuntimeError(f"mtd write 失败: {stderr}", )
    if "OK" not in stdout:
        raise RuntimeError(f"mtd write 未确认: stdout={stdout[:200]}")
    log("mtd write 完成并已 sync")

    # 4. SSH reboot
    log("Step 4/4: reboot")
    try:
        ssh_cmd(router_ip, ssh_pwd, "reboot", timeout=5)
    except subprocess.TimeoutExpired:
        log("reboot 已发出（连接中断，符合预期）")
    log("路由器将重启，自定义 uboot (FIP) 接管后自动 TFTP 拉取 recovery")

    return {
        "ip": router_ip,
        "uboot_file": uboot_file,
        "file_size": file_size,
        "md5": local_md5,
        "target_mtd": TARGET_MTD,
        "reboot": True,
        "next_step": (
            "运行步骤 5 从 initramfs sysupgrade 到完整 OpenWrt: "
            "python3 5.sysupgrade_openwrt.py --debug"
        ),
    }


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "flash_uboot",
        "description": "AX3000T 步骤 4：刷自定义 uboot (FIP) 到 FIP 分区（AX3000T 独有步骤）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP（stock 固件）"},
            {"name": "--ssh-pwd", "type": "string", "default": DEFAULT_SSH_PWD,
             "required": False, "description": "SSH 密码"},
            {"name": "--file", "type": "string", "default": "",
             "required": False, "description": "uboot .fip 文件路径（默认 files/ 下的 bl31-uboot.fip）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 4.flash_uboot.py",
            "python3 4.flash_uboot.py --file files/immortalwrt-...-bl31-uboot.fip --debug",
        ],
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX3000T 步骤 4：刷自定义 uboot (FIP) 到 FIP 分区",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 4.flash_uboot.py\n"
            "  python3 4.flash_uboot.py --file files/immortalwrt-...-bl31-uboot.fip --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help=f"SSH 密码（默认: {DEFAULT_SSH_PWD}）")
    p.add_argument("--file", default="",
                   help="uboot .fip 文件路径（默认 files/ 下的 bl31-uboot.fip）")
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

    uboot_file = args.file or DEFAULT_UBOOT_FILE
    try:
        data = flash_uboot(args.ip, args.ssh_pwd, uboot_file, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        reason = "mtd_write_failed" if "mtd write" in str(e) else ""
        emit_err(str(e), reason=reason, recoverable=False)
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
