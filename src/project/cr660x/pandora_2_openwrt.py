#!/usr/bin/env python3
# cr660x/pandora_2_openwrt.py — pb-boot/breed 已启动 → HTTP 传 initramfs → OpenWrt
#
# 适用: 路由器已刷 pb-boot/breed (192.168.1.1 /upload.cgi)
#       前面步骤 (开 SSH → 传 pb-boot → mtd write → 重启进 uboot) 已手动完成
# 流程: POST initramfs → 等 initramfs OpenWrt → sysupgrade 正式固件
#
# 输出: stdout=单个 JSON, stderr=--debug 时日志

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "pandora_2_openwrt"
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


def run_script(cmd: list, label: str) -> dict:
    log(f"[{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"{label} 无输出: {result.stderr[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} 非 JSON: {stdout[:200]}") from e
    if not data.get("ok"):
        raise RuntimeError(f"{label} 失败: {data.get('error', 'unknown')}")
    log(f"[{label}] 成功")
    return data.get("data", {})


def main() -> int:
    global DEBUG
    p = argparse.ArgumentParser(
        description="pb-boot/breed → HTTP 传 initramfs → OpenWrt",
        epilog="示例:\n  python3 pandora_2_openwrt.py --initramfs files/initramfs-kernel.bin\n"
               "  python3 pandora_2_openwrt.py --initramfs files/initramfs-kernel.bin "
               "--sysupgrade files/sharewifi_1.0.7.bin",
    )
    p.add_argument("--ip", default="192.168.1.1",
                   help="uboot IP (默认 192.168.1.1)")
    p.add_argument("--initramfs", required=True,
                   help="initramfs-kernel.bin 本地路径")
    p.add_argument("--sysupgrade", default="",
                   help="正式 sysupgrade 固件路径 (不传则只烧 initramfs)")
    p.add_argument("--ssh-pwd", default="root",
                   help="SSH root 密码 (默认 root)")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    DEBUG = args.debug

    initramfs = os.path.abspath(args.initramfs) if not os.path.isabs(args.initramfs) else args.initramfs
    if not os.path.isfile(initramfs):
        emit_err(f"initramfs 文件不存在: {initramfs}", reason="file_not_found")
        return 1

    sysupgrade = ""
    if args.sysupgrade:
        sysupgrade = os.path.abspath(args.sysupgrade) if not os.path.isabs(args.sysupgrade) else args.sysupgrade
        if not os.path.isfile(sysupgrade):
            emit_err(f"sysupgrade 文件不存在: {sysupgrade}", reason="file_not_found")
            return 1

    try:
        # ========== 阶段 1: POST initramfs 到 uboot ==========
        log(f"POST {initramfs} → http://{args.ip}/upload.cgi ...")
        curl_cmd = [
            "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "-X", "POST",
            "-F", f"firmware=@{initramfs}",
            f"http://{args.ip}/upload.cgi",
        ]
        log(f"curl: {' '.join(curl_cmd)}")
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=60)
        http_code = result.stdout.strip()
        log(f"curl 返回 HTTP {http_code}")
        if http_code not in ("200", "302"):
            raise RuntimeError(f"uboot upload.cgi 返回 HTTP {http_code}: {result.stderr[:200]}")

        log("initramfs 已上传到 uboot, uboot 正在写入 flash...")
        steps_done = ["uboot_upload"]

        # 等 uboot 写完 + 重启 (~15-30s)
        log("等待 uboot 写入完成 (30s)...")
        time.sleep(30)
        steps_done.append("uboot_write_wait")

        # ========== 阶段 2: 调用 initramfs_2_standard.py ==========
        if sysupgrade:
            log("调用 initramfs_2_standard.py 烧正式固件...")
            cmd = [
                sys.executable,
                os.path.join(SCRIPT_DIR, "initramfs_2_standard.py"),
                "--ip", args.ip,
                "--ssh-pwd", args.ssh_pwd,
                "--file", sysupgrade,
            ]
            if DEBUG:
                cmd.append("--debug")
            data = run_script(cmd, "initramfs_2_standard")
            steps_done.append("initramfs_2_standard")
            emit_ok({
                "ip": args.ip,
                "initramfs": os.path.basename(initramfs),
                "sysupgrade": os.path.basename(sysupgrade),
                "steps": steps_done,
            })
        else:
            emit_ok({
                "ip": args.ip,
                "initramfs": os.path.basename(initramfs),
                "sysupgrade": "none",
                "steps": steps_done,
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
