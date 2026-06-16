#!/usr/bin/env python3
# cr660x/initramfs_2_standard.py — initramfs OpenWrt 已启动后，烧写正式固件
#
# 适用: uboot 刷完 initramfs 后 / all_official_2_openwrt 的后半段
# 前置: 路由器在 initramfs OpenWrt (192.168.1.1), SSH 可用
# 后置: 正式 OpenWrt (有持久 rootfs)
#
# 输出: stdout=单个 JSON, stderr=--debug 时日志

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "initramfs_2_standard"
DEBUG = False


def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error, "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def ping_host(ip: str, timeout: int = 2) -> bool:
    try:
        subprocess.run(["ping", "-c", "1", "-W", str(timeout), ip],
                       capture_output=True, timeout=timeout + 2, check=True)
        return True
    except Exception:
        return False


def wait_ping_up(ip: str, timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if ping_host(ip, 2):
            log(f"{ip} ping 通 (≈{round(time.time()-start,1)}s)")
            return True
        time.sleep(2)
    return False


def wait_ping_down(ip: str, timeout: int = 60) -> bool:
    log(f"等待 {ip} 离线 (timeout={timeout}s)...")
    for i in range(timeout):
        if not ping_host(ip, 1):
            log(f"{ip} 已离线 (≈{i}s)")
            return True
        time.sleep(1)
    return False


def wait_port_open(ip: str, port: int, timeout: int = 60) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            return True
        except Exception:
            time.sleep(2)
    return False


def run_script(cmd: list, label: str) -> dict:
    log(f"[{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"{label} 无输出 (exit={result.returncode}): {result.stderr[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} 非 JSON: {stdout[:200]}") from e
    if not data.get("ok"):
        raise RuntimeError(f"{label} 失败: {data.get('error', 'unknown')}"
                           + (f" (reason: {data.get('reason', '')})" if data.get('reason') else ""))
    return data.get("data", {})


def main() -> int:
    global DEBUG
    p = argparse.ArgumentParser(
        description="initramfs OpenWrt → sysupgrade 正式固件",
        epilog="示例:\n  python3 initramfs_2_standard.py --file files/sharewifi_1.0.7.bin\n"
               "  python3 all_official_2_openwrt.py | python3 initramfs_2_standard.py",
    )
    p.add_argument("--ip", default="192.168.1.1",
                   help="initramfs OpenWrt IP (默认 192.168.1.1)")
    p.add_argument("--ssh-pwd", default="root",
                   help="SSH root 密码 (默认 root)")
    p.add_argument("--file", required=True,
                   help="sysupgrade 固件路径 (本地文件)")
    p.add_argument("--timeout", type=int, default=180,
                   help="总超时秒 (默认 180)")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    DEBUG = args.debug

    ip = args.ip
    file_path = os.path.abspath(args.file) if not os.path.isabs(args.file) else args.file
    if not os.path.isfile(file_path):
        emit_err(f"固件文件不存在: {file_path}", reason="file_not_found")
        return 1

    try:
        # 1. 等 OpenWrt ping 通
        log(f"等待 {ip} 上线...")
        if not wait_ping_up(ip, min(args.timeout, 120)):
            raise RuntimeError(f"{ip} 在 120s 内未 ping 通")

        # 2. 等 SSH 端口
        if not wait_port_open(ip, 22, 60):
            raise RuntimeError(f"{ip}:22 SSH 端口 60s 内未开放")

        log("OpenWrt initramfs 就绪")

        # 3. sysupgrade 正式固件
        data = run_script(
            [sys.executable,
             os.path.join(SCRIPT_DIR, "7.firmware_upload_on_openwrt.py"),
             "--ip", ip, "--ssh-pwd", args.ssh_pwd, "--file", file_path],
            "7.firmware_upload_on_openwrt"
        )
        # 4. 验证 reboot 触发: 等 IP 离线
        log(f"sysupgrade 触发, 等待 {ip} 离线确认刷写完成...")
        if wait_ping_down(ip, 60):
            log(f"{ip} 已离线, 刷写完成!")
        else:
            log(f"{ip} 60s 内未离线 (可能同 IP 启动), 继续")

        emit_ok({
            "ip": ip,
            "local_file": file_path,
            "remote_file": data.get("remote_file", ""),
            "action": "sysupgrade",
            "next_boot": "正式 OpenWrt (有持久 rootfs)",
        })
        return 0

    except RuntimeError as e:
        emit_err(str(e), reason="ssh_failed")
        return 1
    except Exception as e:
        emit_err(str(e), reason="unknown")
        return 1


if __name__ == "__main__":
    sys.exit(main())
