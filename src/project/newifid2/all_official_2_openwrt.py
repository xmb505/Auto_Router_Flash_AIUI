#!/usr/bin/env python3
# all_official_2_openwrt.py — Newifi D2 官方固件 → OpenWrt 全自动刷机
#
# 编排: all_official_2_breed → all_breed_auto_flash
#       (stock → breed 注入)    (breed → initramfs → sysupgrade → OpenWrt)
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621A
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "all_official_2_openwrt"
DEBUG = False


# ============ 日志 / 输出 ============

def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, failed_step: str = "",
             steps_done: list = None) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "failed_step": failed_step,
           "steps_done": steps_done or []}
    print(json.dumps(out, ensure_ascii=False))


# ============ subprocess 调用 ============

def run_script(cmd: list, label: str) -> dict:
    log(f"[{label}] 运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"{label} 无输出 (exit={result.returncode}), "
            f"stderr: {result.stderr[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} 输出非 JSON: {stdout[:200]}") from e

    if not data.get("ok"):
        raise RuntimeError(f"{label} 失败: {data.get('error', 'unknown')}")

    log(f"[{label}] 成功")
    return data.get("data", {})


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Newifi D2 官方固件 → OpenWrt 全自动刷机",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 all_official_2_openwrt.py\n"
            "  python3 all_official_2_openwrt.py --pwd 12345678 --debug\n"
        ),
    )
    p.add_argument("--pwd", default=None,
                   help="路由器管理密码（不传则自动探测，默认 admin）")
    p.add_argument("--config", default=None,
                   help="all_breed_auto_flash.ini 路径（默认: 同目录）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "Newifi D2 官方固件 → OpenWrt 全自动刷机",
        "args": [
            {"name": "--pwd", "type": "string", "default": None,
             "required": False,
             "description": "路由器管理密码（不传则 check_init 探测，默认 admin）"},
            {"name": "--config", "type": "string", "default": None,
             "required": False,
             "description": "all_breed_auto_flash.ini 配置文件路径"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（透传给子脚本）"},
        ],
        "examples": [
            "python3 all_official_2_openwrt.py",
            "python3 all_official_2_openwrt.py --pwd 12345678 --debug",
        ],
        "pipeline": ["all_official_2_breed", "all_breed_auto_flash"],
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


# ============ 主流程 ============

def main() -> int:
    global DEBUG

    if "--help-json" in sys.argv:
        help_json_schema()
        return 0

    args = build_argparse().parse_args()
    DEBUG = args.debug

    steps_done = []
    total_start = time.time()

    try:
        # 1. stock → breed 注入
        log("=== 阶段 1/2: all_official_2_breed ===")
        cmd1 = [sys.executable,
                os.path.join(SCRIPT_DIR, "all_official_2_breed.py")]
        if args.pwd is not None:
            cmd1 += ["--pwd", args.pwd]
        if DEBUG:
            cmd1.append("--debug")

        breed_data = run_script(cmd1, "all_official_2_breed")
        steps_done.append("all_official_2_breed")

        # breed 注入后等 Web 就绪，10s 余量由 breed_auto_flash 内部处理
        log("breed 注入完成，进入刷固件阶段...")

        # 2. breed → initramfs → sysupgrade → OpenWrt
        log("=== 阶段 2/2: all_breed_auto_flash ===")
        cmd2 = [sys.executable,
                os.path.join(SCRIPT_DIR, "all_breed_auto_flash.py")]
        if args.config:
            cmd2 += ["--config", args.config]
        if DEBUG:
            cmd2.append("--debug")

        flash_data = run_script(cmd2, "all_breed_auto_flash")
        steps_done.append("all_breed_auto_flash")

    except RuntimeError as e:
        step_names = {0: "all_official_2_breed",
                      1: "all_breed_auto_flash"}
        failed_step = step_names.get(len(steps_done),
                                     str(e).split()[0] if str(e) else "unknown")
        emit_err(str(e), failed_step=failed_step,
                 steps_done=steps_done)
        return 1

    total_sec = round(time.time() - total_start, 1)
    emit_ok({
        "steps": steps_done,
        "total_duration_sec": total_sec,
        "breed_phase": breed_data,
        "flash_phase": flash_data,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
