#!/usr/bin/env python3
# AX6 步骤 4：通过官方 API 上传并刷写固件（升级/降级通用）
#
# 适用机型: Redmi AX6 (RA69) — IPQ8071A
# 前置:    路由器已初始化 + 一个有效 stok（步骤 2 输出）
# 后置:    路由器自动重启，新固件上线（无需 SSH，全程走 stock API）
# 链路:    upload_rom → syslock?flashtype=upload&downgrade=1
#                  → flash_permission → flash_rom?custom=1&recovery=1
# 来源:    old_coding/Auto_Flash_Router/AX6/downgrade.py
#
# ⚠️  本脚本无脑刷，固件版本检查交给路由器后端（syslock?downgrade=1 永远给通行）。
#     flash_rom?recovery=1 同时清空 NVRAM 配置，升级/降级都清。
#     上游要保证传入的 .bin 是合法小米固件格式（不是 sysupgrade.tar 之类）。
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ 常量（仅网络层默认） ============
DEFAULT_ROUTER_IP = "192.168.31.1"   # 小米 DHCP 网关默认
STEP_NAME = "official_upgrade"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）

# 各阶段超时（秒）—— 路由器上传和刷机都慢
UPLOAD_TIMEOUT = 180
SYSLOCK_TIMEOUT = 15
PERM_TIMEOUT = 15
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


def emit_err(error: str) -> None:
    print(json.dumps({"ok": False, "step": STEP_NAME, "error": error},
                     ensure_ascii=False))


# ============ 4 步 API 调用 ============
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


def syslock_unlock(base_url: str, stok: str) -> int:
    """调 /web/syslock 拿到刷机锁。返回 HTTP 状态码。

    参数:
      flashtype=upload —— 走的是 multipart 上传链路（vs flashtype=url 走 URL OTA）
      downgrade=1      —— 永远带，升级/降级都加；不带的话固件版本检查会卡新版刷旧版，
                          反正加 1 不会影响升新版本，留着统一省心
    """
    url = (f"{base_url}/cgi-bin/luci/;stok={stok}"
           f"/web/syslock?flashtype=upload&downgrade=1")
    with urllib.request.urlopen(url, timeout=SYSLOCK_TIMEOUT) as resp:
        return resp.status


def check_flash_permission(base_url: str, stok: str) -> dict:
    """GET /api/xqsystem/flash_permission 确认有刷机权限。"""
    url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqsystem/flash_permission"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=PERM_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def trigger_flash(base_url: str, stok: str) -> dict:
    """GET /api/xqsystem/flash_rom 触发刷机。路由器将自动重启。

    参数:
      custom=1    —— 允许刷非官方（uboot-mod、ImmortalWrt 等）固件
      recovery=1  —— 清除 NVRAM/配置一并刷（升级/降级都加，等同"恢复出厂 + 刷入"）
    """
    url = (f"{base_url}/cgi-bin/luci/;stok={stok}"
           f"/api/xqsystem/flash_rom?custom=1&recovery=1")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=FLASH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 主流程 ============
def official_upgrade(router_ip: str, stok: str, fw_path: str) -> dict:
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
    log("Step 1/4: 上传固件")
    r = upload_firmware(base_url, stok, fw_data)
    if r.get("code") != 0:
        raise RuntimeError(f"上传固件被拒 (code={r.get('code')}): {r}")
    log("上传完成")

    # 2. syslock
    log("Step 2/4: 拿刷机锁 (syslock)")
    status = syslock_unlock(base_url, stok)
    if status != 200:
        raise RuntimeError(f"syslock 返回 HTTP {status}（stok 可能已过期）")
    log("syslock OK")

    # 3. 刷机许可
    log("Step 3/4: 检查刷机许可 (flash_permission)")
    r = check_flash_permission(base_url, stok)
    if r.get("code") != 0:
        raise RuntimeError(f"刷机许可被拒 (code={r.get('code')}): {r}")
    log("刷机许可通过")

    # 4. 触发刷写
    log("Step 4/4: 触发刷写 (flash_rom)—— 路由器将自动重启")
    r = trigger_flash(base_url, stok)
    if r.get("code") != 0:
        raise RuntimeError(f"flash_rom 被拒 (code={r.get('code')}): {r}")
    log("flash_rom OK，等待路由器重启")

    return {
        "ip": router_ip,
        "firmware": fw_path,
        "size_bytes": len(fw_data),
        "will_reboot": True,
    }


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX6 步骤 4：通过官方 API 上传并刷写固件（升级/降级通用，清 NVRAM）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 4.official_upgrade.py --stok <token> --file files/RA69_1.1.3.bin\n"
            "  python3 2.login_get_stok.py | python3 4.official_upgrade.py --file files/RA69_1.1.3.bin\n"
            "  python3 2.login_get_stok.py | python3 4.official_upgrade.py --file files/RA69_1.1.3.bin --debug\n"
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
    args = parse_args()
    DEBUG = args.debug

    try:
        stok = args.stok or read_stok_from_stdin()
    except RuntimeError as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1

    try:
        data = official_upgrade(args.ip, stok, args.file)
    except (RuntimeError, urllib.error.URLError, socket.timeout, OSError) as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
