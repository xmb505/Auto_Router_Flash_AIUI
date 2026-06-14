#!/usr/bin/env python3
# all_official_2_breed.py — 官方固件一键注入 breed
#
# 流程: [check_init] → login_get_sid → ssh_enable → breed_inject
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
STEP_NAME = "all_official_2_breed"
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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


# ============ 命令构造 ============

def build_check_init_cmd() -> list:
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "check_init.py")]
    if DEBUG:
        cmd.append("--debug")
    return cmd


def build_login_cmd(pwd: str) -> list:
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "2.login_get_sid.py"),
           "--pwd", pwd]
    if DEBUG:
        cmd.append("--debug")
    return cmd


def build_ssh_enable_cmd(sid: str) -> list:
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "3.ssh_enable.py"),
           "--sid", sid]
    if DEBUG:
        cmd.append("--debug")
    return cmd


def build_breed_inject_cmd(pwd: str) -> list:
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "4.breed_inject.py"),
           "--pwd", pwd]
    if DEBUG:
        cmd.append("--debug")
    return cmd


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Newifi D2 官方固件一键注入 breed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 all_official_2_breed.py          # 用默认密码 admin\n"
            "  python3 all_official_2_breed.py --pwd 12345678\n"
        ),
    )
    p.add_argument("--pwd", default=None,
                   help="路由器管理密码（不传则自动探测，默认 admin）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "Newifi D2 官方固件一键注入 breed",
        "args": [
            {"name": "--pwd", "type": "string", "default": None,
             "required": False,
             "description": "路由器管理密码（不传则 check_init 探测，默认 admin）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（透传给子脚本）"},
        ],
        "examples": [
            "python3 all_official_2_breed.py",
            "python3 all_official_2_breed.py --pwd 12345678 --debug",
        ],
        "pipeline": ["check_init", "login_get_sid", "ssh_enable",
                     "breed_inject"],
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
        # 1. 确定密码
        if args.pwd is not None:
            pwd = args.pwd
            log(f"使用指定密码")
        else:
            log("=== 步骤 1: check_init ===")
            check_data = run_script(build_check_init_cmd(), "check_init")
            steps_done.append("check_init")

            is_inited = check_data.get("is_inited", False)
            if is_inited:
                emit_err(
                    "路由器已初始化，请先恢复出厂设置再运行此脚本",
                    failed_step="check_init",
                    steps_done=steps_done,
                )
                return 1

            pwd = "admin"
            log(f"路由器未初始化，使用默认密码: {pwd}")

        # 2. 登录获取 SID
        log("=== 步骤 2: login_get_sid ===")
        login_data = run_script(build_login_cmd(pwd), "login_get_sid")
        steps_done.append("login_get_sid")
        sid = login_data.get("sid", "")
        if not sid:
            raise RuntimeError("login_get_sid 未返回 sid")
        log(f"获取到 SID: {sid[:8]}...")

        # 3. 开启 SSH
        log("=== 步骤 3: ssh_enable ===")
        run_script(build_ssh_enable_cmd(sid), "ssh_enable")
        steps_done.append("ssh_enable")

        # 4. 注入 breed
        log("=== 步骤 4: breed_inject ===")
        run_script(build_breed_inject_cmd(pwd), "breed_inject")
        steps_done.append("breed_inject")

    except RuntimeError as e:
        step_names = {0: "check_init", 1: "login_get_sid",
                      2: "ssh_enable", 3: "breed_inject"}
        failed_step = step_names.get(len(steps_done),
                                     str(e).split()[0] if str(e) else "unknown")
        emit_err(str(e), failed_step=failed_step,
                 steps_done=steps_done)
        return 1

    total_sec = round(time.time() - total_start, 1)
    emit_ok({
        "steps": steps_done,
        "total_duration_sec": total_sec,
        "router_ip_breed": "192.168.1.1",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
