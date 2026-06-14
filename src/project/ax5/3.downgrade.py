#!/usr/bin/env python3
# AX5 步骤 3：通过官方 API 上传并刷写降级固件
#
# 适用机型: Redmi AX5 (RA67 / RM1800) — IPQ6000
# 前置:    路由器已初始化 + 一个有效 stok（步骤 2 输出）
# 后置:    路由器自动重启，降级固件上线（NVRAM 被清，inited 回到 0）
# 链路:    upload_rom → flash_rom?custom=1&recovery=1
# 来源:    old_coding/Auto_Flash_Router/AX5/downgrade.py
#          相比 AX6 的 4.official_upgrade.py 简化为 2 步（无 syslock / flash_permission）
#
# ⚠️  AX5 固件（1.4.31 等）的刷写 API 只需 upload + flash，
#     不像 AX6 需要 syslock + flash_permission 中间步骤。
#     flash_rom?recovery=1 同时清空 NVRAM 配置。
#
# 输出:    stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import json
import random
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # 小米 DHCP 网关默认
STEP_NAME = "downgrade"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）

# 各阶段超时（秒）—— 路由器上传和刷机都慢
UPLOAD_TIMEOUT = 180
FLASH_TIMEOUT = 120


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ 2 步 API 调用 ============
def upload_firmware(base_url: str, stok: str, fw_data: bytes) -> dict:
    """POST multipart/form-data 上传固件到 /api/xqsystem/upload_rom。"""
    boundary = b"----WebKitFormBoundary" + str(random.randint(10**8, 10**9 - 1)).encode()
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="image"; filename="firmware.bin"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        + fw_data +
        b"\r\n--" + boundary + b"--\r\n"
    )
    url = f"{base_url}/uploadfile/cgi-bin/luci/;stok={stok}/api/xqsystem/upload_rom"
    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary.decode())
    with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def trigger_flash(base_url: str, stok: str) -> dict:
    """GET /api/xqsystem/flash_rom 触发刷机。路由器将自动重启。

    参数:
      custom=1    —— 允许刷非官方固件
      recovery=1  —— 清除 NVRAM/配置一并刷（降级后 inited 回到 0）
    """
    url = (f"{base_url}/cgi-bin/luci/;stok={stok}"
           f"/api/xqsystem/flash_rom?custom=1&recovery=1")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=FLASH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 主流程 ============
def downgrade(router_ip: str, stok: str, fw_path: str) -> dict:
    base_url = f"http://{router_ip}"

    # 0. 读本地固件
    log(f"读取固件 {fw_path}")
    try:
        with open(fw_path, "rb") as f:
            fw_data = f.read()
    except FileNotFoundError:
        raise RuntimeError(f"固件文件未找到: {fw_path}")
    log(f"固件大小: {len(fw_data)} bytes")

    # 1. 上传
    log("Step 1/2: 上传固件")
    r = upload_firmware(base_url, stok, fw_data)
    if r.get("code") != 0:
        raise RuntimeError(f"上传固件被拒 (code={r.get('code')}): {r}")
    is_downgrade = r.get("downgrade", False)
    log(f"上传完成 (downgrade={is_downgrade})")

    # 2. 触发刷写（AX5 无需 syslock + flash_permission）
    log("Step 2/2: 触发刷写 (flash_rom) —— 路由器将自动重启")
    r = trigger_flash(base_url, stok)
    if r.get("code") != 0:
        raise RuntimeError(f"flash_rom 被拒 (code={r.get('code')}): {r}")
    log("flash_rom OK，等待路由器重启")

    return {
        "ip": router_ip,
        "firmware": fw_path,
        "size_bytes": len(fw_data),
        "is_downgrade": is_downgrade,
        "will_reboot": True,
    }


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "downgrade",
        "description": "AX5 步骤 3：通过官方 API 上传并刷写降级固件（2步简化版）",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--stok", "type": "string", "default": "",
             "required": False, "description": "stok（来自步骤 2；空则从 stdin 读上游 JSON）"},
            {"name": "--file", "type": "string", "default": None,
             "required": True, "description": "固件文件路径"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 3.downgrade.py --stok <token> --file files/RA67_1.0.26.bin",
            "python3 2.login_get_stok.py | python3 3.downgrade.py --file files/RA67_1.0.26.bin",
        ],
        "stdin_contract": {
            "expects": "上游 JSON（含 data.stok），可用 --stok 替代",
            "produces": "降级结果 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX5 步骤 3：通过官方 API 上传并刷写降级固件（2步简化版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 3.downgrade.py --stok <token> --file files/RA67_1.0.26.bin\n"
            "  python3 2.login_get_stok.py | python3 3.downgrade.py --file files/RA67_1.0.26.bin\n"
            "  python3 2.login_get_stok.py | python3 3.downgrade.py --file files/RA67_1.0.26.bin --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--stok", default="",
                   help="stok（来自步骤 2；空则从 stdin 读上游 JSON）")
    p.add_argument("--file", required=True,
                   help="固件文件路径（必传，相对或绝对路径均可）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默，仅输出 JSON）")
    return p.parse_args()


def read_stok_from_stdin() -> str:
    """从上游管道 JSON 读 stok。上游 ok:false 时把 error 透传出来。"""
    if sys.stdin.isatty():
        raise RuntimeError("未通过 stdin 管道传入上游 JSON，也未传 --stok")
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("stdin 为空（上游没产出 JSON）")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"上游 stdin 不是合法 JSON: {e}")
    if d.get("ok") is False:
        raise RuntimeError(f"上游失败: {d.get('error', '未知错误')}")
    stok = d.get("data", {}).get("stok", "")
    if not stok:
        raise RuntimeError(f"上游 JSON 没有 data.stok 字段: {d}")
    return stok


def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug

    try:
        stok = args.stok or read_stok_from_stdin()
    except RuntimeError as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1

    try:
        data = downgrade(args.ip, stok, args.file)
    except (RuntimeError, urllib.error.URLError, socket.timeout, OSError) as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
