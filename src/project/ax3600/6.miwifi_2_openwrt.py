#!/usr/bin/env python3
# 6.miwifi_2_openwrt.py — 烧镜像到指定 mtd
# (小米 stock 切 OpenWrt/ImmortalWrt 的**烧入**步骤)
#
# ⚠️ 前提: .ubi/.bin 文件**已经**通过 5.firmware_upload_on_miwifi.sh 上传到 /tmp/
#    本脚本**只**负责: SSH 烧 + 输出 JSON
#    **不**切启动分区——那是 set_miwifi_uboot_partition.sh 的事
#
# 流程:
#   1. SSH 探测当前活跃 mtd (cat /proc/cmdline 解析 ubi.mtd=)  — 安全检查用
#   2. 验证 --part 与当前 mtd 关系 (对侧烧才安全)
#   3. SSH 验证 /tmp/<file-name> 已存在
#   4. SSH 跑 ubiformat /dev/mtdN -q -y -f /tmp/<file-name>  (调 miwifi_ssh.sh)
#   5. **不**自动 reboot — 留给用户手动 reset / ssh reboot
#
# 使用:
#   # 1) 上传文件
#   ./5.firmware_upload_on_miwifi.sh --file files/openwrt.ubi
#   # 2) 烧到指定 mtd (对侧烧更安全)
#   python3 6.miwifi_2_openwrt.py --file-name openwrt.ubi --part 1
#   # 3) 切启动分区 (可选, 用 set_miwifi_uboot_partition.sh)
#   ./set_miwifi_uboot_partition.sh --part 1
#   # 4) reboot 激活
#   ./miwifi_ssh.sh --cmd 'reboot'
#
# 输出: stdout = 单个 JSON {"ok": bool, "step": "miwifi_2_openwrt", "data"|"error": ...}
#       stderr = 时间戳日志 (仅 --debug 开启时)
#       exit  = 0 成功 / 1 失败

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

STEP_NAME = "miwifi_2_openwrt"
DEFAULT_IP = "192.168.31.1"
DEFAULT_SSH_PWD = "root"
DEFAULT_TIMEOUT = 30
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO", debug: bool = False) -> None:
    if not debug:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error: str) -> None:
    print(json.dumps({"ok": False, "step": STEP_NAME, "error": error}, ensure_ascii=False))


# ============ 复用: 同目录工具脚本 ============
def run_tool(tool: str, args: list, debug: bool = False) -> tuple[bool, str, str]:
    """调同目录工具脚本, 返回 (ok, stdout, stderr)"""
    path = os.path.join(SCRIPT_DIR, tool)
    if not os.path.isfile(path):
        return False, "", f"tool not found: {path}"
    result = subprocess.run([path] + args, capture_output=True, text=True)
    if debug:
        log(f"{tool} ec={result.returncode}", debug=debug)
        if result.stdout:
            log(f"  stdout: {result.stdout[:300]}", debug=debug)
        if result.stderr:
            log(f"  stderr: {result.stderr[:300]}", debug=debug)
    return result.returncode == 0, result.stdout, result.stderr


# ============ Step 1: 探测当前活跃 mtd ============
def probe_current_mtd(ip: str, ssh_pwd: str, timeout: int = 10,
                      debug: bool = False) -> tuple[str | None, str | None]:
    """SSH 跑 'cat /proc/cmdline' 解析 ubi.mtd= 决定当前 mtd"""
    ok, raw, err = run_tool("miwifi_ssh.sh", [
        "--ip", ip, "--pwd", ssh_pwd, "--cmd", "cat /proc/cmdline",
    ], debug=debug)
    if not ok:
        return None, f"ssh failed: {err[:200]}"
    try:
        arr = json.loads(raw)
        if not arr or not arr[0].get("ok"):
            return None, f"ssh cmd failed: {arr[0].get('stderr', '') if arr else 'no output'}"
        cmdline = arr[0]["stdout"].strip()
    except json.JSONDecodeError as e:
        return None, f"parse ssh output: {e}"

    if "ubi.mtd=rootfs_1" in cmdline:
        return "mtd13", None
    if "ubi.mtd=rootfs" in cmdline:
        return "mtd12", None
    return None, f"unexpected cmdline: {cmdline[:200]}"


# ============ Step 2: 验证 /tmp/<file-name> 存在 ============
def verify_remote_file(file_name: str, ip: str, ssh_pwd: str,
                      debug: bool = False) -> tuple[bool, str]:
    """SSH 检查 /tmp/<file_name> 是否存在 + 大小"""
    cmd = f"ls -la /tmp/{file_name}"
    ok, raw, err = run_tool("miwifi_ssh.sh", [
        "--ip", ip, "--pwd", ssh_pwd, "--cmd", cmd,
    ], debug=debug)
    if not ok:
        return False, f"ssh failed: {err[:200]}"
    try:
        arr = json.loads(raw)
        if not arr or not arr[0].get("ok"):
            stderr = arr[0].get("stderr", "") if arr else "no output"
            return False, f"ls failed: {stderr[:200]}"
        out = arr[0].get("stdout", "").strip()
        if not out or "No such file" in out:
            return False, f"file not found: /tmp/{file_name}"
        return True, out
    except json.JSONDecodeError as e:
        return False, f"parse ssh output: {e}"


# ============ Step 3: ubiformat ============
def ubiformat_mtd(file_name: str, part: int, ip: str, ssh_pwd: str,
                  debug: bool = False) -> tuple[bool, str]:
    """SSH 跑 ubiformat /dev/mtdN -q -y -f /tmp/<file_name>

    -q 必须加: ubiformat 默认输出进度条 (\\r + 百分比),
    miwifi_ssh.sh --cmd 收到后 json.loads 报 "Invalid control character"."""
    mtd_dev = "/dev/mtd12" if part == 0 else "/dev/mtd13"
    cmd = f"ubiformat {mtd_dev} -q -y -f /tmp/{file_name}"
    log(f"ubiformat {mtd_dev} -q -y -f /tmp/{file_name}", debug=debug)
    ok, raw, err = run_tool("miwifi_ssh.sh", [
        "--ip", ip, "--pwd", ssh_pwd, "--cmd", cmd,
    ], debug=debug)
    if not ok:
        return False, f"ssh failed: {err[:200]}"
    try:
        arr = json.loads(raw)
        if not arr or not arr[0].get("ok"):
            stderr = arr[0].get("stderr", "") if arr else "no output"
            return False, f"ubiformat failed: {stderr[:400]}"
        return True, arr[0].get("stdout", "").strip()
    except json.JSONDecodeError as e:
        return False, f"parse ssh output: {e}"


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="烧镜像到指定 mtd (文件已通过 5.firmware_upload_on_miwifi.sh 上传到 /tmp/)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 1) 上传 (单独一步)\n"
            "  ./5.firmware_upload_on_miwifi.sh --file files/immortalwrt-25.12.0-redmi_ax6-stock.ubi\n"
            "  # 2) 自动选对侧 mtd (推荐: 当前活跃 mtd12 → 烧 mtd13, 反之亦然)\n"
            "  python3 6.miwifi_2_openwrt.py --file-name immortalwrt-25.12.0-redmi_ax6-stock.ubi\n"
            "\n"
            "  # 当前在 OpenWrt 192.168.1.1 时, 烧回 mtd12\n"
            "  python3 6.miwifi_2_openwrt.py --file-name openwrt.ubi --part 0 --ip 192.168.1.1\n"
            "\n"
            "  # Dry-run, 只探测不烧\n"
            "  python3 6.miwifi_2_openwrt.py --file-name openwrt.ubi --probe-only\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP (默认: {DEFAULT_IP})")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help=f"SSH 密码 (默认: {DEFAULT_SSH_PWD})")
    p.add_argument("--part", type=int, choices=[0, 1], default=None,
                   help="烧到 mtd12 (part=0) 或 mtd13 (part=1)。不传时自动探测当前活跃 mtd 并选对侧")
    p.add_argument("--file-name", required=True,
                   help="/tmp/ 下的文件名 (已通过 5.firmware_upload_on_miwifi.sh 上传)")
    p.add_argument("--debug", action="store_true",
                   help="详细日志 (默认静默)")
    p.add_argument("--probe-only", action="store_true",
                   help="只探测当前 mtd, 不真烧 (dry-run)")
    p.add_argument("--yes", action="store_true",
                   help="跳过 confirm (覆盖当前活跃 mtd 时仍要这个)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒 (默认: {DEFAULT_TIMEOUT})")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    debug = args.debug

    # 步骤 0: 探测当前活跃 mtd (安全检查 / 自动选对侧)
    current_mtd, err = probe_current_mtd(args.ip, args.ssh_pwd, timeout=10, debug=debug)
    if err:
        emit_err(f"探测当前 mtd 失败: {err}")
        return 1

    # 自动选对侧: 不传 --part 时, 当前 mtd12 → target mtd13, 反之亦然
    if args.part is None:
        args.part = 1 if current_mtd == "mtd12" else 0
        log(f"--part 未传, 自动选中对侧: part={args.part}", debug=debug)

    target_mtd = "mtd12" if args.part == 0 else "mtd13"
    log(f"参数: ip={args.ip} part={args.part} file_name={args.file_name}", debug=debug)
    log(f"当前活跃 mtd: {current_mtd}, 目标: {target_mtd}", debug=debug)

    writing_to_inactive = (current_mtd != target_mtd)
    safety_warning = None

    if not writing_to_inactive:
        safety_warning = (
            f"⚠️ 目标 mtd={target_mtd} == 当前活跃 mtd, "
            f"会**覆盖**当前 rootfs!"
        )
        if not args.yes and not args.probe_only:
            emit_err(safety_warning + " (加 --yes 强制继续, 或用 --probe-only 只探测)")
            return 1
        log(safety_warning, level="WARN", debug=debug)

    # --probe-only: 探测完就退出
    if args.probe_only:
        emit_ok({
            "probe_only": True,
            "current_mtd": current_mtd,
            "target_mtd": target_mtd,
            "writing_to_inactive": writing_to_inactive,
            "safety_warning": safety_warning,
            "file_name": args.file_name,
            "remote_path": f"/tmp/{args.file_name}",
            "would_run": ["verify_remote_file", "ubiformat"],
        })
        return 0

    # 步骤 2: 验证 /tmp/<file-name> 存在
    ok, ls_out = verify_remote_file(args.file_name, args.ip, args.ssh_pwd, debug=debug)
    if not ok:
        emit_err(f"文件不存在或不可访问: {ls_out}")
        return 1
    log(f"文件已存在: {ls_out[:200]}", debug=debug)

    # 步骤 3: ubiformat (核心烧)
    ok, ubi_out = ubiformat_mtd(args.file_name, args.part, args.ip, args.ssh_pwd, debug=debug)
    if not ok:
        emit_err(f"ubiformat 失败: {ubi_out}")
        return 1
    log(f"ubiformat 完成", debug=debug)

    # 步骤 4: 报告 (不切 flag, 不自动 reboot)
    emit_ok({
        "ip": args.ip,
        "part": args.part,
        "target_mtd": target_mtd,
        "current_mtd": current_mtd,
        "writing_to_inactive": writing_to_inactive,
        "safety_warning": safety_warning,
        "file_name": args.file_name,
        "remote_path": f"/tmp/{args.file_name}",
        "ubiformat_output_excerpt": ubi_out[:300],
        "next_step": (
            "1) 可选切启动分区: ./set_miwifi_uboot_partition.sh --part {0|1}  (默认对上 --part)\n"
            f"2) reboot 激活: ./miwifi_ssh.sh --ip {args.ip} --cmd 'reboot' 或物理 reset"
        ),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
