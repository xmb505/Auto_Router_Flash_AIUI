#!/usr/bin/env python3
# all_official_2_openwrt.py — AX3000T 官方固件 → OpenWrt 全自动刷机
#
# 适用机型: 小米 AX3000T (RD03) — MT7981 (Filogic 820)
#
# 流程（基于 2026-06-14 实机验证）:
#   ping 检测 → init_info → 验证硬件
#   1.official_init → 2.login_get_stok → 3.enable_ssh
#   4.flash_uboot (刷 FIP + 自动重启 → TFTP initramfs)
#   5.sysupgrade_openwrt (initramfs → 完整 OpenWrt)
#   [可选 6.custom_openwrt]
#
# 前置条件: 主机需运行 TFTP 服务器（提供 initramfs-recovery.itb）
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import configparser
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "all_official_2_openwrt"
DEBUG = False

# ============ 常量 ============
DEFAULT_STOCK_IP = "192.168.31.1"
DEFAULT_OPENWRT_IP = "192.168.1.1"
INIT_INFO_URL = "http://{}/cgi-bin/luci/api/xqsystem/init_info"
INIT_INFO_TIMEOUT = 5
REBOOT_WAIT_TIMEOUT = 180
SSH_WAIT_TIMEOUT = 90
SSH_RETRY_MAX = 3
SSH_RETRY_WAIT = 15
OPENWRT_WAIT_TIMEOUT = 180

DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "all_official_2_openwrt.ini")


# ============ 配置读取 ============

def read_config(path: str) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    result = {}
    for section in cfg.sections():
        for key, val in cfg[section].items():
            result[f"{section}.{key}"] = val
    return result


# ============ 日志 / 输出 ============

def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True,
             failed_step: str = "", steps_done: list = None) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "failed_step": failed_step,
           "steps_done": steps_done or [],
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ 网络/等待工具 ============

def ping_host(ip: str, timeout: int = 3) -> bool:
    try:
        subprocess.run(["ping", "-c", "1", "-W", str(timeout), ip],
                       capture_output=True, timeout=timeout + 2, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def wait_ping_down(ip: str, timeout: int = 30) -> bool:
    log(f"等待 {ip} 离线 (timeout={timeout}s)...")
    for i in range(timeout):
        if not ping_host(ip, 1):
            log(f"{ip} 已离线 (≈{i}s)")
            return True
        time.sleep(1)
    log(f"等待离线超时 ({timeout}s)")
    return False


def wait_ping_up(ip: str, timeout: int = 120) -> bool:
    log(f"等待 {ip} 上线 (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        if ping_host(ip, 2):
            elapsed = round(time.time() - start, 1)
            log(f"{ip} 已上线 (≈{elapsed}s)")
            return True
        time.sleep(2)
    log(f"等待上线超时 ({timeout}s)")
    return False


def wait_port_down(ip: str, port: int, timeout: int = 30) -> bool:
    """等待端口关闭"""
    log(f"等待 {ip}:{port} 关闭 (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((ip, port), timeout=3):
                time.sleep(2)
        except (socket.timeout, ConnectionRefusedError, OSError):
            elapsed = round(time.time() - start, 1)
            log(f"{ip}:{port} 已关闭 (≈{elapsed}s)")
            return True
    log(f"等待 {ip}:{port} 关闭超时")
    return False


def wait_port_open(ip: str, port: int, timeout: int = 90) -> bool:
    log(f"等待 {ip}:{port} 开放 (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            elapsed = round(time.time() - start, 1)
            log(f"{ip}:{port} 已开放 (≈{elapsed}s)")
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(2)
    log(f"等待 {ip}:{port} 超时 ({timeout}s)")
    return False


def fetch_init_info(ip: str) -> dict:
    url = INIT_INFO_URL.format(ip)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=INIT_INFO_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"获取 init_info 失败: {e}")


def wait_http_ready(ip: str, timeout: int = 120) -> None:
    log("等待 HTTP 服务就绪...")
    for i in range(timeout):
        try:
            info = fetch_init_info(ip)
            if "inited" in info:
                log(f"HTTP 就绪 (≈{i}s), inited={info.get('inited')}")
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("等待 HTTP 服务就绪超时")


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
        err_msg = data.get("error", "unknown")
        reason = data.get("reason", "")
        raise RuntimeError(
            f"{label} 失败: {err_msg}"
            + (f" (reason: {reason})" if reason else ""))

    log(f"[{label}] 成功")
    return data.get("data", {})


def run_shell_script(script_name: str, args: list, label: str) -> dict:
    cmd = [os.path.join(SCRIPT_DIR, script_name)] + args
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

    if isinstance(data, list):
        for item in data:
            if not item.get("ok"):
                err_msg = item.get("stderr", item.get("cmd", "unknown"))
                raise RuntimeError(f"{label} 命令失败: {err_msg}")
        return data[0] if data else {}

    if not data.get("ok"):
        err_msg = data.get("error", "unknown")
        raise RuntimeError(f"{label} 失败: {err_msg}")
    return data.get("data", {k: v for k, v in data.items() if k != "ok"})


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AX3000T 官方固件 → OpenWrt 全自动刷机",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 all_official_2_openwrt.py\n"
            "  python3 all_official_2_openwrt.py --pwd 12345678\n"
            "  python3 all_official_2_openwrt.py --config my.ini --debug\n"
        ),
    )
    p.add_argument("--pwd", default="12345678",
                   help="管理员密码（默认: 12345678，即 init 设的密码）")
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help=f"INI 配置文件路径（默认: {DEFAULT_CONFIG}）")
    p.add_argument("--step", type=int, default=1, choices=[1, 2, 3, 4, 5, 6],
                   help="起始步骤（1=从头, 5=initramfs 模式, 仅刷 sysupgrade）")
    p.add_argument("--ip", default=DEFAULT_STOCK_IP,
                   help=f"路由器 stock IP (默认: {DEFAULT_STOCK_IP})")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（透传给子脚本）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "AX3000T 官方固件 → OpenWrt 全自动刷机",
        "args": [
            {"name": "--pwd", "type": "string", "default": "12345678",
             "required": False,
             "description": "管理员密码（默认 12345678，即 init 设的密码）"},
            {"name": "--config", "type": "file", "default": DEFAULT_CONFIG,
             "required": False,
             "description": "INI 配置文件路径"},
            {"name": "--step", "type": "int", "default": 1,
             "required": False,
             "description": "起始步骤（1=从头, 5=initramfs 模式）"},
            {"name": "--ip", "type": "string", "default": DEFAULT_STOCK_IP,
             "required": False,
             "description": "路由器 stock IP"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（透传给子脚本）"},
        ],
        "config_format": "INI: [firmware].uboot_file, [firmware].sysupgrade_file, [firmware].overlay_file (可选)",
        "examples": [
            "python3 all_official_2_openwrt.py",
            "python3 all_official_2_openwrt.py --debug",
        ],
        "pipeline": [
            "ping", "init_info", "1.official_init", "2.login_get_stok",
            "3.enable_ssh", "4.flash_uboot",
            "5.sysupgrade_openwrt", "6.custom_openwrt (optional)",
        ],
        "note": "需要主机运行 TFTP 服务器提供 initramfs-recovery.itb",
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

    stock_ip = args.ip
    openwrt_ip = DEFAULT_OPENWRT_IP
    pwd = args.pwd
    step = args.step

    # 读 INI 配置
    cfg = read_config(args.config)
    uboot_file = cfg.get("firmware.uboot_file", "")
    sysupgrade_file = cfg.get("firmware.sysupgrade_file", "")
    overlay = cfg.get("firmware.overlay_file", "") or None

    if not uboot_file or not sysupgrade_file:
        emit_err("INI 需要配置 firmware.uboot_file 和 firmware.sysupgrade_file",
                 reason="file_not_found", failed_step="config")
        return 1

    def resolve(p):
        return os.path.join(SCRIPT_DIR, p) if not os.path.isabs(p) else p

    uboot_file = resolve(uboot_file)
    sysupgrade_file = resolve(sysupgrade_file)
    if overlay:
        overlay = resolve(overlay)

    steps_done = []
    total_start = time.time()

    try:
        # ========== 分水岭: --step 5 跳过 stock 阶段 ==========
        if step >= 5:
            log(f"initramfs 模式 (--step {step})，跳过 stock 阶段")
        else:
            # ========== 阶段 0: 检测路由器 ==========
            log("=== 阶段 0: 检测路由器 ===")

            if not ping_host(stock_ip, 3):
                raise RuntimeError(f"路由器 {stock_ip} 不可达（ping 超时）")
            log(f"路由器 {stock_ip} 在线")
            steps_done.append("ping_ok")

            info = fetch_init_info(stock_ip)
            model = info.get("model", "")
            hardware = info.get("hardware", "")
            romversion = info.get("romversion", "")
            inited = info.get("inited")
            log(f"型号: {model}, 硬件: {hardware}, 版本: {romversion}, inited: {inited}")

            if "rd03" not in model.lower() and "ax3000t" not in hardware.lower():
                raise RuntimeError(
                    f"硬件不匹配: 期望 AX3000T/RD03, 实际 model={model}")
            log("硬件验证通过: AX3000T")
            steps_done.append("verified_ax3000t")

            if inited == 1:
                raise RuntimeError(
                    "路由器已初始化 (inited=1), 不知道管理密码。"
                    "请物理 Reset 路由器（按住 RESET 孔 5-10 秒上电）"
                    "回到工厂态后再试")
            steps_done.append("factory_ok")

            # ========== 阶段 1: 出厂初始化 ==========
            log("=== 阶段 1: 出厂初始化 ===")
            init_data = run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "1.official_init.py"),
                 "--ip", stock_ip,
                 "--admin-pwd", pwd,
                 "--debug"] if DEBUG else
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "1.official_init.py"),
                 "--ip", stock_ip,
                 "--admin-pwd", pwd],
                "1.official_init"
            )
            init_version = init_data.get("firmware_version", romversion)
            log(f"初始化完成, 固件版本: {init_version}")
            steps_done.append("1.official_init")

            # ========== 阶段 2: 登录拿 stok ==========
            log("=== 阶段 2: 登录获取 stok ===")
            login_cmd = [sys.executable,
                         os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
                         "--ip", stock_ip, "--pwd", pwd]
            if DEBUG:
                login_cmd.append("--debug")
            login_data = run_script(login_cmd, "2.login_get_stok")
            stok = login_data.get("stok", "")
            if not stok:
                raise RuntimeError("登录失败: 未获取到 stok")
            steps_done.append("2.login_get_stok")

            # ========== 阶段 3: 启用 SSH ==========
            log("=== 阶段 3: 注入开 SSH (start_binding) ===")
            ssh_cmd = [sys.executable,
                       os.path.join(SCRIPT_DIR, "3.enable_ssh.py"),
                       "--ip", stock_ip, "--stok", stok]
            if DEBUG:
                ssh_cmd.append("--debug")
            ssh_data = run_script(ssh_cmd, "3.enable_ssh")
            log(f"SSH 启用: port={ssh_data.get('ssh_port', '?')}")
            steps_done.append("3.enable_ssh")

            time.sleep(10)
            if not wait_port_open(stock_ip, 22, SSH_WAIT_TIMEOUT):
                raise RuntimeError("SSH 端口 22 未在预期时间内开放")
            log("SSH 端口 22 就绪")

            # ========== 阶段 4: 刷 FIP uboot ==========
            log("=== 阶段 4: 刷 FIP uboot ===")
            flash_uboot_cmd = [sys.executable,
                               os.path.join(SCRIPT_DIR, "4.flash_uboot.py"),
                               "--ip", stock_ip, "--file", uboot_file]
            if DEBUG:
                flash_uboot_cmd.append("--debug")
            run_script(flash_uboot_cmd, "4.flash_uboot")
            log("FIP 写入完成，路由器自动重启（TFTP 拉 initramfs）")
            steps_done.append("4.flash_uboot")

            # flash_uboot 重启后等 60s 让 uboot TFTP 拉 initramfs
            log("等待 initramfs 启动 (60s)...")
            time.sleep(60)

        # ========== 阶段 5: sysupgrade（initramfs → 完整 OpenWrt） ==========
        log("=== 阶段 5: sysupgrade 到完整 OpenWrt ===")

        # 5.sysupgrade_openwrt.py 内部等 initramfs SSH → scp → sysupgrade → 等重启 → 等上线
        sysupgrade_cmd = [sys.executable,
                          os.path.join(SCRIPT_DIR, "5.sysupgrade_openwrt.py"),
                          "--ip", openwrt_ip,
                          "--file", sysupgrade_file]
        if DEBUG:
            sysupgrade_cmd.append("--debug")
        sysupgrade_data = run_script(sysupgrade_cmd, "5.sysupgrade_openwrt")
        log(f"sysupgrade 完成: reboot={sysupgrade_data.get('reboot')}")
        steps_done.append("5.sysupgrade_openwrt")

        # 等 SSH 断连（sysupgrade 触发的重启）再上线
        log("等待 OpenWrt SSH 上线...")
        wait_port_down(openwrt_ip, 22, 30)
        if wait_port_open(openwrt_ip, 22, OPENWRT_WAIT_TIMEOUT):
            log("OpenWrt SSH 就绪")
        else:
            log("OpenWrt SSH 超时", level="WARN")

        # ========== 阶段 6: 应用 overlay（可选，重试最多 3 次） ==========
        if overlay:
            log("=== 阶段 6: 应用 overlay ===")
            for attempt in range(1, 4):
                try:
                    overlay_cmd = [sys.executable,
                                   os.path.join(SCRIPT_DIR, "6.custom_openwrt.py"),
                                   "--ip", openwrt_ip,
                                   "--file", overlay]
                    if DEBUG:
                        overlay_cmd.append("--debug")
                    run_script(overlay_cmd, f"6.custom_openwrt (attempt {attempt})")
                    steps_done.append("6.custom_openwrt")
                    break
                except RuntimeError as e:
                    if attempt < 3:
                        log(f"Overlay 失败，重试 ({attempt}/3): {e}")
                        time.sleep(10)
                    else:
                        log(f"Overlay 最终失败: {e}", level="WARN")

    except RuntimeError as e:
        failed_step = steps_done[-1] if steps_done else "pre_check"
        emit_err(str(e), reason="unknown",
                 failed_step=failed_step,
                 steps_done=steps_done)
        return 1

    total_sec = round(time.time() - total_start, 1)
    emit_ok({
        "steps": steps_done,
        "total_duration_sec": total_sec,
        "model": "AX3000T",
        "target": "openwrt",
        "firmware": os.path.basename(sysupgrade_file),
        "overlay_applied": overlay is not None,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
