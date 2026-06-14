#!/usr/bin/env python3
# all_official_2_openwrt.py — AX5 官方固件 → LibWrt/OpenWrt 全自动刷机
#
# 适用机型: Redmi AX5 (RA67 / RM1800) — IPQ6000
#
# 流程（基于 2026-06-14 实机验证）:
#   ping 检测 → get_router_info → 验证硬件
#   1.official_init (工厂态) → 2.login_get_stok → [可选 3.downgrade]
#   [等重启] → 1.official_init (1.0.26) → 2.login_get_stok
#   4.enable_ssh → 5.firmware_upload → 6.miwifi_2_openwrt
#   set_miwifi_uboot_partition → reboot
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
DEFAULT_ROUTER_IP = "192.168.31.1"
INIT_INFO_URL = "http://{}/cgi-bin/luci/api/xqsystem/init_info"
INIT_INFO_TIMEOUT = 5
REBOOT_WAIT_TIMEOUT = 120
SSH_WAIT_TIMEOUT = 90
OPENWRT_WAIT_TIMEOUT = 120

# 需要降级的固件版本（只 1.0.26 免降级）
KNOWN_GOOD_VERSION = "1.0.26"


DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "all_official_2_openwrt.ini")


# ============ 配置读取 ============

def read_config(path: str) -> dict:
    """configparser 读 INI，返回扁平 dict。"""
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
    """ping 检测主机是否在线"""
    try:
        subprocess.run(["ping", "-c", "1", "-W", str(timeout), ip],
                       capture_output=True, timeout=timeout + 2, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def wait_ping_down(ip: str, timeout: int = 60) -> bool:
    """等待主机离线（重启时 ping 断连）"""
    log(f"等待 {ip} 离线 (timeout={timeout}s)...")
    for i in range(timeout):
        if not ping_host(ip, 1):
            log(f"{ip} 已离线 (≈{i}s)")
            return True
        time.sleep(1)
    log(f"等待离线超时 ({timeout}s)")
    return False


def wait_ping_up(ip: str, timeout: int = 120) -> bool:
    """等待主机上线（重启后 ping 通）"""
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


def wait_port_open(ip: str, port: int, timeout: int = 90) -> bool:
    """等待端口开放（如 SSH 22）"""
    log(f"等待 {ip}:{port} 开放 (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            elapsed = round(time.time() - start, 1)
            log(f"{ip}:{port} 已开放 (≈{elapsed}s)")
            return True
        except (OSError, ConnectionRefusedError, socket.timeout):
            time.sleep(2)
    log(f"等待 {ip}:{port} 超时 ({timeout}s)")
    return False


def fetch_init_info(ip: str) -> dict:
    """GET init_info 返回 JSON"""
    url = INIT_INFO_URL.format(ip)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=INIT_INFO_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"获取 init_info 失败: {e}")


# ============ subprocess 调用 ============

def run_script(cmd: list, label: str) -> dict:
    """运行子脚本，解析 JSON，校验 ok 字段"""
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
    """运行 .sh 脚本，解析 stdout JSON（支持对象或数组）。"""
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

    # 处理 JSON 数组（如 miwifi_ssh.sh 返回 [{ok:..., cmd:...}])
    if isinstance(data, list):
        for item in data:
            if not item.get("ok"):
                err_msg = item.get("stderr", item.get("cmd", "unknown"))
                raise RuntimeError(f"{label} 命令失败: {err_msg}")
        return data[0] if data else {}
    # 处理 JSON 对象
    if not data.get("ok"):
        err_msg = data.get("error", "unknown")
        raise RuntimeError(f"{label} 失败: {err_msg}")
    # shell 脚本返回扁平 JSON（无 data 字段），取 data 或全量返回
    return data.get("data", {k: v for k, v in data.items() if k != "ok"})


# ============ 版本检查 ============

def needs_downgrade(romversion: str) -> bool:
    """判断是否需要降级 — 只 1.0.26 免降级"""
    return romversion != KNOWN_GOOD_VERSION


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AX5 官方固件 → LibWrt/OpenWrt 全自动刷机",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 all_official_2_openwrt.py --pwd 12345678\n"
            "  python3 all_official_2_openwrt.py\n"
            "  python3 all_official_2_openwrt.py --config my.ini --debug\n"
        ),
    )
    p.add_argument("--pwd", default="12345678",
                   help="管理员密码（默认: 12345678，即 init 设的密码）")
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help=f"INI 配置文件路径（默认: {DEFAULT_CONFIG}）")
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP (默认: {DEFAULT_ROUTER_IP})")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（透传给子脚本）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "AX5 官方固件 → LibWrt/OpenWrt 全自动刷机",
        "args": [
            {"name": "--pwd", "type": "string", "default": "12345678",
             "required": False,
             "description": "管理员密码（默认 12345678，即 init 设的密码）"},
            {"name": "--config", "type": "file", "default": DEFAULT_CONFIG,
             "required": False,
             "description": "INI 配置文件路径"},
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False,
             "description": "路由器 IP"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（透传给子脚本）"},
        ],
        "config_format": ("INI: [firmware].ubi_file, "
                          "[firmware].downgrade_file (可选)"),
        "examples": [
            "python3 all_official_2_openwrt.py",
            "python3 all_official_2_openwrt.py --pwd 12345678",
            "python3 all_official_2_openwrt.py --config my.ini --debug",
        ],
        "pipeline": [
            "ping", "get_router_info", "1.official_init", "2.login_get_stok",
            "3.downgrade (optional)", "4.enable_ssh",
            "5.firmware_upload", "6.miwifi_2_openwrt",
            "set_miwifi_uboot_partition", "reboot",
        ],
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

    ip = args.ip
    pwd = args.pwd

    # 读 INI 配置
    cfg = read_config(args.config)
    firmware = cfg.get("firmware.ubi_file", "")
    downgrade_file = cfg.get("firmware.downgrade_file", "") or None

    if not firmware:
        emit_err("INI 中未配置 firmware.ubi_file", reason="file_not_found",
                 failed_step="config")
        return 1
    firmware = os.path.join(SCRIPT_DIR, firmware) if not os.path.isabs(firmware) else firmware
    if downgrade_file:
        downgrade_file = os.path.join(SCRIPT_DIR, downgrade_file) if not os.path.isabs(downgrade_file) else downgrade_file

    steps_done = []
    total_start = time.time()

    try:
        # ========== 阶段 0: 检测路由器 ==========
        log("=== 阶段 0: 检测路由器 ===")

        # 0.1 ping 检测
        if not ping_host(ip, 3):
            raise RuntimeError(f"路由器 {ip} 不可达（ping 超时）")
        log(f"路由器 {ip} 在线")
        steps_done.append("ping_ok")

        # 0.2 get_router_info
        info = fetch_init_info(ip)
        model = info.get("model", "")
        hardware = info.get("hardware", "")
        romversion = info.get("romversion", "")
        inited = info.get("inited")
        log(f"型号: {model}, 硬件: {hardware}, 版本: {romversion}, inited: {inited}")

        if "ra67" not in hardware.lower() and "ra67" not in model.lower():
            raise RuntimeError(
                f"硬件不匹配: 期望 RA67, 实际 hardware={hardware}, model={model}")
        log("硬件验证通过: RA67")
        steps_done.append("verified_ra67")

        # inited=1 → 不知道密码，无法继续
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
             "--ip", ip,
             "--admin-pwd", pwd,
             "--debug"] if DEBUG else
            [sys.executable,
             os.path.join(SCRIPT_DIR, "1.official_init.py"),
             "--ip", ip,
             "--admin-pwd", pwd],
            "1.official_init"
        )
        init_version = init_data.get("firmware_version", romversion)
        log(f"初始化完成, 固件版本: {init_version}")
        steps_done.append("1.official_init")

        # ========== 阶段 2: 登录拿 stok ==========
        log("=== 阶段 2: 登录获取 stok ===")
        if DEBUG:
            login_cmd = [sys.executable,
                         os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
                         "--ip", ip, "--pwd", pwd, "--debug"]
        else:
            login_cmd = [sys.executable,
                         os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
                         "--ip", ip, "--pwd", pwd]
        login_data = run_script(login_cmd, "2.login_get_stok")
        stok = login_data.get("stok", "")
        if not stok:
            raise RuntimeError("登录失败: 未获取到 stok")
        steps_done.append("2.login_get_stok")

        # ========== 阶段 3: 降级（可选） ==========
        if downgrade_file:
            log("=== 阶段 3: 降级固件 ===")
            if not needs_downgrade(romversion):
                log(f"版本 {romversion} 不需要降级，跳过")
            else:
                if DEBUG:
                    downgrade_cmd = [sys.executable,
                                     os.path.join(SCRIPT_DIR, "3.downgrade.py"),
                                     "--ip", ip, "--stok", stok,
                                     "--file", downgrade_file, "--debug"]
                else:
                    downgrade_cmd = [sys.executable,
                                     os.path.join(SCRIPT_DIR, "3.downgrade.py"),
                                     "--ip", ip, "--stok", stok,
                                     "--file", downgrade_file]
                downgrade_data = run_script(downgrade_cmd, "3.downgrade")
                log("降级触发, 等待路由器重启...")
                steps_done.append("3.downgrade")

                # 等待重启: ping down → ping up
                wait_ping_down(ip, 30)
                if not wait_ping_up(ip, REBOOT_WAIT_TIMEOUT):
                    raise RuntimeError("降级后等待路由器上线超时")
                log("路由器 ping 通，等待 HTTP 服务就绪...")
                # 轮询 init_info 直到 HTTP 返回有效 JSON
                http_ready = False
                for i in range(REBOOT_WAIT_TIMEOUT):
                    try:
                        info = fetch_init_info(ip)
                        if "inited" in info:
                            log(f"HTTP 服务就绪 (≈{i}s), inited={info.get('inited')}")
                            http_ready = True
                            break
                    except Exception:
                        pass
                    time.sleep(1)
                if not http_ready:
                    raise RuntimeError("降级后等待 HTTP 服务就绪超时")

                # 重新初始化（降级清 NVRAM, inited→0）
                log("=== 阶段 3b: 降级后重初始化 ===")
                init_data = run_script(
                    [sys.executable,
                     os.path.join(SCRIPT_DIR, "1.official_init.py"),
                     "--ip", ip, "--admin-pwd", pwd],
                    "1.official_init (re-init)"
                )
                steps_done.append("1.official_init_post_downgrade")

                # 重新登录拿 stok
                login_data = run_script(login_cmd, "2.login_get_stok (re-login)")
                stok = login_data.get("stok", "")
                if not stok:
                    raise RuntimeError("降级后重登录失败: 未获取到 stok")
                steps_done.append("2.login_get_stok_post_downgrade")
        else:
            log("跳过降级")

        # ========== 阶段 4: 启用 SSH ==========
        log("=== 阶段 4: 注入开 SSH ===")
        if DEBUG:
            ssh_cmd = [sys.executable,
                       os.path.join(SCRIPT_DIR, "4.enable_ssh.py"),
                       "--ip", ip, "--stok", stok, "--debug"]
        else:
            ssh_cmd = [sys.executable,
                       os.path.join(SCRIPT_DIR, "4.enable_ssh.py"),
                       "--ip", ip, "--stok", stok]
        ssh_data = run_script(ssh_cmd, "4.enable_ssh")
        log(f"SSH 启用: port={ssh_data.get('ssh_port', '?')}")
        steps_done.append("4.enable_ssh")

        # 等待 SSH 端口就绪
        if not wait_port_open(ip, 22, SSH_WAIT_TIMEOUT):
            raise RuntimeError("SSH 端口 22 未在预期时间内开放")
        log("SSH 端口 22 就绪")

        # ========== 阶段 5: 上传固件 ==========
        log("=== 阶段 5: 上传固件到 /tmp/ ===")
        if DEBUG:
            upload_cmd = [sys.executable,
                          os.path.join(SCRIPT_DIR, "5.firmware_upload_on_miwifi.py"),
                          "--ip", ip, "--file", firmware, "--debug"]
        else:
            upload_cmd = [sys.executable,
                          os.path.join(SCRIPT_DIR, "5.firmware_upload_on_miwifi.py"),
                          "--ip", ip, "--file", firmware]
        upload_data = run_script(upload_cmd, "5.firmware_upload")
        fname = upload_data.get("target",
                                os.path.basename(firmware))
        steps_done.append("5.firmware_upload")

        # ========== 阶段 6: 烧镜像 ==========
        log("=== 阶段 6: ubiformat 烧固件 ===")
        if DEBUG:
            flash_cmd = [sys.executable,
                         os.path.join(SCRIPT_DIR, "6.miwifi_2_openwrt.py"),
                         "--ip", ip, "--file-name", fname, "--debug"]
        else:
            flash_cmd = [sys.executable,
                         os.path.join(SCRIPT_DIR, "6.miwifi_2_openwrt.py"),
                         "--ip", ip, "--file-name", fname]
        flash_data = run_script(flash_cmd, "6.miwifi_2_openwrt")
        target_mtd = flash_data.get("target_mtd", "?")
        part = flash_data.get("part",
                              "1" if "mtd19" in str(target_mtd) else "0")
        log(f"固件写入 {target_mtd}")
        steps_done.append("6.miwifi_2_openwrt")

        # ========== 阶段 7: 切启动分区 ==========
        log("=== 阶段 7: 切启动分区 ===")
        switch_data = run_shell_script(
            "set_miwifi_uboot_partition.sh",
            ["--ip", ip, "--part", str(part)],
            "set_miwifi_uboot_partition"
        )
        log(f"切到 part={part}")
        steps_done.append("set_miwifi_uboot_partition")

        # ========== 阶段 8: reboot ==========
        log("=== 阶段 8: reboot 激活 ===")
        reboot_data = run_shell_script(
            "miwifi_ssh.sh",
            ["--ip", ip, "--cmd", "reboot"],
            "reboot"
        )
        steps_done.append("reboot")

        # ========== 阶段 9: 等待 OpenWrt 上线 ==========
        log("等待 OpenWrt 上线 (192.168.1.1)...")
        if wait_ping_up("192.168.1.1", OPENWRT_WAIT_TIMEOUT):
            log("OpenWrt 已上线")
        else:
            log("OpenWrt 上线超时（可能是 stock IP 未变），继续")

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
        "model": "RA67",
        "target": "openwrt",
        "firmware": os.path.basename(firmware),
        "downgraded": downgrade_file is not None,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
