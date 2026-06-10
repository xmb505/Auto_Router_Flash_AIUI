#!/usr/bin/env python3
# 7.custom_openwrt.py — 步骤 7: 应用自定义 OpenWrt overlay (主题/配置等)
#
# 适用机型: Redmi AX3600 (R3600) — 已刷 ImmortalWrt/OpenWrt
# 默认 IP:  192.168.1.1  (OpenWrt 默认网段)
# 默认 SSH: root 空密码 (ImmortalWrt 出厂)
#
# 流程: scp 上传 overlay-new.tar.gz → /tmp
#       SSH: tar -xzf → cp -a overlay/* /overlay/upper/ → 清理
#       SSH: reboot
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 时间戳日志 (仅 --debug 开启)
#       exit  = 0 成功 / 1 失败 / 2 参数错 / 3 网络错 / 4 认证错

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

STEP_NAME = "custom_openwrt"
DEFAULT_IP = "192.168.1.1"
DEFAULT_SSH_PWD = ""
DEFAULT_TIMEOUT = 60
DEFAULT_REMOTE_NAME = "overlay-new.tar.gz"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）


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


# ============ SCP 上传 ============
def scp_upload(local_path: str, remote_name: str, ip: str, ssh_pwd: str,
               timeout: int) -> tuple[bool, str]:
    """scp 上传到 /tmp/<remote_name>; 返回 (ok, error_msg)

    不用 miwifi_ssh.sh: OpenWrt 用 ED25519 host key, 走原生 sshpass 更直接
    保留 -O 绕过 sftp (dropbear sftp 支持不稳)
    +ssh-rsa 不冲突 — 仅追加算法, 不限制
    """
    remote_path = f"/tmp/{remote_name}"
    log(f"scp {local_path} → root@{ip}:{remote_path}")
    cmd = [
        "sshpass", "-p", ssh_pwd,
        "scp", "-O",
        "-oHostKeyAlgorithms=+ssh-rsa",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        local_path, f"root@{ip}:{remote_path}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, ""


# ============ SSH 命令 ============
def ssh_cmd(ip: str, ssh_pwd: str, cmd: str, timeout: int) -> tuple[bool, str]:
    """sshpass + ssh 跑一条命令; 返回 (ok, stdout+stderr)

    timeout 到期不算错 — reboot 后连接会断, 这正是预期
    """
    log(f"ssh root@{ip} {cmd[:60]}{'...' if len(cmd) > 60 else ''}")
    ssh_cmd = [
        "sshpass", "-p", ssh_pwd,
        "ssh",
        "-oHostKeyAlgorithms=+ssh-rsa",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        f"root@{ip}", cmd,
    ]
    proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, proc.stdout.strip()


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="应用自定义 OpenWrt overlay (主题/配置等) 到路由器, 自动重启",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 默认 (OpenWrt 默认 IP, 本地 files/overlay-new.tar.gz)\n"
            "  python3 ./7.custom_openwrt.py --file files/overlay-new.tar.gz\n"
            "\n"
            "  # 显式 IP\n"
            "  python3 ./7.custom_openwrt.py --ip 192.168.1.1 --file files/overlay-new.tar.gz\n"
            "\n"
            "  # SSH 密码不为空时 (罕见, ImmortalWrt 默认免密)\n"
            "  python3 ./7.custom_openwrt.py --file files/overlay-new.tar.gz --ssh-pwd mypass\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"OpenWrt 路由器 IP (默认: {DEFAULT_IP})")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help="SSH 密码 (默认: 空, ImmortalWrt 默认免密)")
    p.add_argument("--file", required=True,
                   help="本地 overlay tar.gz 路径 (会被 scp 到 /tmp/)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒 (默认: {DEFAULT_TIMEOUT})")
    p.add_argument("--debug", action="store_true",
                   help="详细日志 (默认静默)")
    return p.parse_args()


# ============ 主流程 ============
def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug
    log(f"参数: ip={args.ip} file={args.file}")

    if not os.path.isfile(args.file):
        emit_err(f"本地文件不存在: {args.file}")
        return 2

    # 步骤 1: scp 上传
    ok, err = scp_upload(args.file, DEFAULT_REMOTE_NAME, args.ip, args.ssh_pwd,
                         timeout=args.timeout)
    if not ok:
        emit_err(f"scp 上传失败: {err}")
        return 3
    log(f"上传完成: /tmp/{DEFAULT_REMOTE_NAME}")

    # 步骤 2: 解压 → 复制到 /overlay/upper → 清理
    extract_cmd = (
        f"cd /tmp && tar -xzf {DEFAULT_REMOTE_NAME} "
        f"&& cp -a overlay/* /overlay/upper/ "
        f"&& rm -rf overlay {DEFAULT_REMOTE_NAME} "
        f"&& echo OK"
    )
    ok, out = ssh_cmd(args.ip, args.ssh_pwd, extract_cmd, timeout=args.timeout)
    if not ok:
        emit_err(f"解压失败: {out}")
        return 1
    if "OK" not in out:
        emit_err(f"解压未确认: stdout={out[:200]}")
        return 1
    log("overlay 已写入 /overlay/upper/")

    # 步骤 3: reboot (连接会断, 算预期超时)
    log("reboot...")
    try:
        ssh_cmd(args.ip, args.ssh_pwd, "reboot", timeout=5)
    except subprocess.TimeoutExpired:
        log("reboot 已发出 (连接中断, 符合预期)")

    emit_ok({
        "ip": args.ip,
        "file": args.file,
        "remote_path": f"/tmp/{DEFAULT_REMOTE_NAME}",
        "extract_marker": "OK",
        "reboot": True,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())