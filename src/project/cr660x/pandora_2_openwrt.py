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
        log(f"POST {initramfs} → http://{args.ip}/upload.cgi (HTTP/0.9)...")
        curl_cmd = [
            "curl", "-s", "--http0.9",
            "-X", "POST",
            "-F", f"firmware=@{initramfs}",
            f"http://{args.ip}/upload.cgi",
        ]
        log(f"curl: POST {os.path.basename(initramfs)} → /upload.cgi")
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=120)
        resp = result.stdout.strip()
        if not resp:
            raise RuntimeError(f"uboot upload.cgi 空响应 (stderr: {result.stderr[:200]})")
        if "上传成功" in resp or "Upload Successful" in resp:
            log("pb-boot 接收固件成功, 开始写入 flash...")
        elif "error" in resp.lower() or "失败" in resp:
            raise RuntimeError(f"uboot 上传失败: {resp[:300]}")
        else:
            log(f"uboot 响应 (未识别关键字): {resp[:200]}")
        steps_done = ["uboot_upload"]

        # ========== 阶段 2: 轮询 status.html 等刷写完成 ==========
        log("轮询 status.html 监控 flash 写入进度...")
        status_url = f"http://{args.ip}/status.html"
        flash_ok = False
        poll_start = time.time()
        poll_timeout = 120
        while time.time() - poll_start < poll_timeout:
            result = subprocess.run(
                ["curl", "-s", "--http0.9", status_url],
                capture_output=True, text=True, timeout=10,
            )
            raw = result.stdout.strip()
            if raw:
                # status.html 返回自定义格式: {status:"writting",progress:"55"}
                # 无引号的 key, 手动解析
                status = ""
                progress = ""
                for part in raw.strip("{}").split(","):
                    part = part.strip()
                    if ":" not in part:
                        continue
                    key, val = part.split(":", 1)
                    key = key.strip().strip('"')
                    val = val.strip().strip('"')
                    if key == "status":
                        status = val
                    elif key == "progress":
                        progress = val
                if progress:
                    log(f"  flash 进度: {progress}%")
                if status == "done":
                    log("flash 写入完成!")
                    flash_ok = True
                    break
                if status == "error":
                    raise RuntimeError(f"pb-boot 刷写失败 (status=error)")
            time.sleep(2)
        if not flash_ok:
            raise RuntimeError(f"pb-boot 刷写超时 ({poll_timeout}s)")
        steps_done.append("flash_done")

        # ========== 阶段 3: 触发 reboot ==========
        log("GET /reboot.cgi 触发重启...")
        subprocess.run(
            ["curl", "-s", "--http0.9", "-o", "/dev/null",
             f"http://{args.ip}/reboot.cgi"],
            timeout=10,
        )
        steps_done.append("uboot_reboot")

        log("pb-boot 重启中, 等待 initramfs OpenWrt 上线...")

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
