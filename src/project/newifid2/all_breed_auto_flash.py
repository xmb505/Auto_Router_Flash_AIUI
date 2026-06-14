#!/usr/bin/env python3
# all_breed_auto_flash.py — Newifi D2 一键 breed → OpenWrt 自动刷机编排器
#
# 编排: breed_enter → breed_flash_firmware → ping 上线 → openwrt_sysupgrade → ping 下线
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621A
# 架构: subprocess 调用现有脚本，解析 JSON stdout，不做 import
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import configparser
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "all_breed_auto_flash"
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "all_breed_auto_flash.ini")
PING_INTERVAL = 3
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


# ============ 核心函数 ============

def read_config(path: str) -> dict:
    """configparser 读 INI，返回扁平 dict。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return {
        "iface": cfg.get("network", "iface", fallback="").strip(),
        "initramfs_file": cfg.get("firmware", "initramfs_file",
                                  fallback="").strip(),
        "sysupgrade_file": cfg.get("firmware", "sysupgrade_file",
                                   fallback="").strip(),
        "password": cfg.get("ssh", "password", fallback="").strip(),
    }


def resolve_path(path: str) -> str:
    """相对路径基于 SCRIPT_DIR 解析。"""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(SCRIPT_DIR, path)


def validate_config(cfg: dict) -> None:
    """校验必填字段和文件存在。"""
    for key in ("initramfs_file", "sysupgrade_file"):
        if not cfg.get(key):
            raise ValueError(f"配置文件缺少必填字段: [firmware].{key}")
    for key in ("initramfs_file", "sysupgrade_file"):
        abs_path = resolve_path(cfg[key])
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"固件文件不存在: {abs_path}")


def run_script(cmd: list, label: str) -> dict:
    """subprocess.run → json.loads(stdout) → 检查 ok，失败 raise RuntimeError。"""
    log(f"[{label}] 运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=600)
    # debug 模式下把子脚本 stderr 转发到本脚本 stderr
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"{label} 无输出 (exit={result.returncode}), "
            f"stderr: {result.stderr[:200]}"
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{label} 输出非 JSON: {stdout[:200]}") from e

    if not data.get("ok"):
        err = data.get("error", "unknown")
        raise RuntimeError(f"{label} 失败: {err}")

    log(f"[{label}] 成功")
    return data.get("data", {})


def wait_ssh(ip: str, port: int = 22, timeout: int = 60) -> float:
    """轮询等待 SSH 端口开放，返回耗时秒。"""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            if s.connect_ex((ip, port)) == 0:
                s.close()
                return round(time.time() - start, 1)
            s.close()
        except Exception:
            pass
        elapsed = int(time.time() - start)
        log(f"SSH {ip}:{port} 未就绪 ({elapsed}s)")
        time.sleep(3)
    raise RuntimeError(f"SSH {ip}:{port} 在 {timeout}s 内未开放")


def wait_ping(ip: str, timeout: int, want_online: bool) -> float:
    """ping -c1 -W2 循环，want_online=True 等上线 / False 等下线，返回耗时秒。"""
    start = time.time()
    consecutive_fail = 0
    while time.time() - start < timeout:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", ip],
                           capture_output=True, timeout=10)
        is_online = (r.returncode == 0)

        if want_online and is_online:
            return round(time.time() - start, 1)
        if not want_online:
            if not is_online:
                consecutive_fail += 1
                if consecutive_fail >= 2:
                    return round(time.time() - start, 1)
            else:
                consecutive_fail = 0

        elapsed = int(time.time() - start)
        state = "online" if is_online else "offline"
        log(f"ping {ip}: {state} ({elapsed}s)")
        time.sleep(PING_INTERVAL)

    verb = "上线" if want_online else "下线"
    raise RuntimeError(f"{ip} 在 {timeout}s 内未{verb}")


# ============ 命令构造 ============

def build_breed_enter_cmd(cfg: dict) -> list:
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "breed_enter.py"),
           "--timeout", "180"]
    if cfg["iface"]:
        cmd += ["--iface", cfg["iface"]]
    if DEBUG:
        cmd.append("--debug")
    return cmd


def build_breed_flash_cmd(cfg: dict) -> list:
    initramfs = resolve_path(cfg["initramfs_file"])
    cmd = [sys.executable,
           os.path.join(SCRIPT_DIR, "5.breed_flash_firmware.py"),
           "--file", initramfs, "--ip", "192.168.1.1"]
    if DEBUG:
        cmd.append("--debug")
    return cmd


def build_sysupgrade_cmd(cfg: dict) -> list:
    sysupgrade = resolve_path(cfg["sysupgrade_file"])
    cmd = [sys.executable,
           os.path.join(SCRIPT_DIR, "6.openwrt_sysupgrade.py"),
           "--file", sysupgrade, "--ip", "192.168.1.1",
           "--ssh-pwd", cfg["password"]]
    if DEBUG:
        cmd.append("--debug")
    return cmd


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Newifi D2 一键 breed → OpenWrt 自动刷机编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 all_breed_auto_flash.py\n"
            "  python3 all_breed_auto_flash.py --config my.ini --debug\n"
        ),
    )
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help=f"INI 配置文件路径（默认: {DEFAULT_CONFIG}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "Newifi D2 一键 breed → OpenWrt 自动刷机编排器",
        "args": [
            {"name": "--config", "type": "string",
             "default": "同目录 all_breed_auto_flash.ini",
             "required": False,
             "description": "INI 配置文件路径"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（透传给子脚本）"},
        ],
        "examples": [
            "python3 all_breed_auto_flash.py",
            "python3 all_breed_auto_flash.py --config my.ini --debug",
        ],
        "config_format": ("INI: [network].iface, "
                          "[firmware].initramfs_file/sysupgrade_file, "
                          "[ssh].password"),
        "pipeline": ["breed_enter", "breed_flash", "ping_online",
                     "sysupgrade", "ping_offline"],
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

    # 读配置
    try:
        cfg = read_config(args.config)
        validate_config(cfg)
    except (FileNotFoundError, ValueError) as e:
        emit_err(str(e))
        return 1

    steps_done = []
    total_start = time.time()

    try:
        # 1. breed_enter
        log("=== 步骤 1/5: breed_enter ===")
        breed_data = run_script(build_breed_enter_cmd(cfg), "breed_enter")
        steps_done.append("breed_enter")

        # 2. 等 breed Web 服务就绪
        log("等待 10s 给 breed Web 服务启动...")
        time.sleep(10)

        # 3. breed_flash_firmware
        log("=== 步骤 3/6: breed_flash_firmware ===")
        flash_data = run_script(build_breed_flash_cmd(cfg),
                                "breed_flash_firmware")
        steps_done.append("breed_flash")

        # 4. 等 initramfs OpenWrt 上线
        log("=== 步骤 4/6: 等待 initramfs 上线 ===")
        ping_online_sec = wait_ping("192.168.1.1", 120, True)
        steps_done.append("ping_online")
        log(f"initramfs 已上线 ({ping_online_sec}s)")

        # 5. 等 dropbear 就绪
        log("=== 步骤 5/7: 等待 SSH 就绪 ===")
        ssh_wait_sec = wait_ssh("192.168.1.1", 22, 60)
        steps_done.append("ssh_ready")
        log(f"SSH 已就绪 ({ssh_wait_sec}s)")

        # 6. sysupgrade
        log("=== 步骤 6/7: openwrt_sysupgrade ===")
        sysup_data = run_script(build_sysupgrade_cmd(cfg),
                                "openwrt_sysupgrade")
        steps_done.append("sysupgrade")

        # 7. 等路由器下线（sysupgrade 后重启）
        log("=== 步骤 7/7: 等待路由器下线 ===")
        ping_offline_sec = wait_ping("192.168.1.1", 180, False)
        steps_done.append("ping_offline")
        log(f"路由器已下线 ({ping_offline_sec}s)")

    except RuntimeError as e:
        failed = steps_done[-1] if steps_done else "unknown"
        # 根据已完成步骤推断失败步骤名
        step_names = {0: "breed_enter", 1: "breed_flash_firmware",
                      2: "wait_ping_online", 3: "wait_ssh_ready",
                      4: "openwrt_sysupgrade", 5: "wait_ping_offline"}
        failed_step = step_names.get(len(steps_done), str(e).split()[0])
        emit_err(str(e), failed_step=failed_step,
                 steps_done=steps_done)
        return 1

    total_sec = round(time.time() - total_start, 1)
    emit_ok({
        "steps": steps_done,
        "total_duration_sec": total_sec,
        "initramfs_file": cfg["initramfs_file"],
        "sysupgrade_file": cfg["sysupgrade_file"],
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
