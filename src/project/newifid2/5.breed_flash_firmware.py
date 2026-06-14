#!/usr/bin/env python3
# 5.breed_flash_firmware.py — Breed Web 刷写固件（上传 + 触发 + 轮询 + 确认重启）
#
# 适用机型: Newifi D2 (新路由3) / Lecoo — MT7621
# 协议: breed Web API (multipart upload + POST 轮询)
# 前置: breed 已激活（breed_enter.py 已完成）
# 后置: 固件已刷写，路由器自动重启到新系统
#
# 输出: stdout = 单个 JSON
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 通用 / 3 网络 / 5 超时

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_IP = "192.168.1.1"
DEFAULT_TIMEOUT = 30
UPLOAD_TIMEOUT = 120
POLL_INTERVAL = 2
REBOOT_PROBE_INTERVAL = 5
REBOOT_PROBE_TIMEOUT = 90
STEP_NAME = "breed_flash_firmware"
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


def emit_err(error: str, reason: str = "unknown",
             recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ HTTP 工具 ============

def http_get(ip: str, path: str, timeout: int) -> tuple[int, dict, str]:
    """GET 请求，返回 (status_code, headers_dict, body_str)。"""
    url = f"http://{ip}{path}"
    log(f"GET {url}")
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            log(f"← HTTP {resp.status} server={headers.get('server', '?')} "
                f"({len(body)} bytes)")
            return resp.status, headers, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        headers = {k.lower(): v for k, v in e.headers.items()}
        log(f"← HTTP {e.code} ({len(body)} bytes)")
        return e.code, headers, body
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}") from e


def http_post_multipart(ip: str, path: str, fields: dict,
                        timeout: int) -> tuple[int, dict, str]:
    """POST multipart/form-data，返回 (status_code, headers_dict, body_str)。"""
    boundary = "----BreedFlashBoundary" + str(int(time.time() * 1000))
    body_parts = []
    for key, value in fields.items():
        body_parts.append(f"--{boundary}".encode())
        if isinstance(value, tuple):
            filename, file_data = value
            body_parts.append(
                f'Content-Disposition: form-data; name="{key}"; '
                f'filename="{filename}"'.encode())
            body_parts.append(b"Content-Type: application/octet-stream")
            body_parts.append(b"")
            body_parts.append(file_data)
        else:
            body_parts.append(
                f'Content-Disposition: form-data; name="{key}"'.encode())
            body_parts.append(b"")
            body_parts.append(value.encode() if isinstance(value, str)
                              else value)
    body_parts.append(f"--{boundary}--".encode())
    body_parts.append(b"")
    body_data = b"\r\n".join(body_parts)

    url = f"http://{ip}{path}"
    log(f"POST {url} ({len(body_data)} bytes)")
    req = urllib.request.Request(url, data=body_data)
    req.add_header("Content-Type",
                   f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            log(f"← HTTP {resp.status} ({len(body)} bytes)")
            return resp.status, headers, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        headers = {k.lower(): v for k, v in e.headers.items()}
        log(f"← HTTP {e.code} ({len(body)} bytes)")
        return e.code, headers, body
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}") from e


def http_post_empty(ip: str, path: str, timeout: int) -> str:
    """POST 空 body（application/x-www-form-urlencoded），返回 body_str。"""
    url = f"http://{ip}{path}"
    req = urllib.request.Request(url, data=b"")
    req.add_header("Content-Type",
                   "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace")[:200]
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}") from e


# ============ 刷机流程 ============

def upload_firmware(ip: str, filepath: str, timeout: int) -> dict:
    """上传固件到 breed /upload.html，返回确认信息。"""
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        file_data = f.read()
    file_size = len(file_data)

    fields = {
        "boot_file": "",
        "fw_check": "1",
        "fw_file": (filename, file_data),
        "flash_layout": "reference",
        "fw_type": "generic",
        "autoreboot": "1",
        "submit": "Upload",
    }

    status, headers, body = http_post_multipart(
        ip, "/upload.html", fields, timeout)

    if status != 200:
        raise RuntimeError(f"上传失败: HTTP {status}")

    if 'has_fw = "1"' not in body and "has_fw" not in body:
        raise RuntimeError("上传响应中未找到固件确认 (has_fw)")

    # 从确认页提取文件大小和 MD5
    size_match = re.search(
        r'<td>大小</td>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>MD5',
        body, re.DOTALL)
    md5_match = re.search(
        r'MD5 校验</td>\s*<td>([a-f0-9]{32})</td>', body, re.DOTALL)

    return {
        "filename": filename,
        "file_size": file_size,
        "md5": md5_match.group(1) if md5_match else None,
    }


def trigger_flash(ip: str, timeout: int) -> None:
    """GET /upgrading.html 触发实际刷写。"""
    status, headers, body = http_get(ip, "/upgrading.html", timeout)
    if status == 404 or "文件未找到" in body:
        raise RuntimeError(
            "/upgrading.html 返回 404，固件可能未正确上传")
    if status != 200:
        raise RuntimeError(f"触发刷写失败: HTTP {status}")
    log("刷写已触发")


def poll_progress(ip: str, timeout: int) -> int:
    """POST 轮询 /upgrade_query.html 直到 100%，返回总耗时秒。"""
    start = time.time()
    last_pct = -1
    while True:
        try:
            resp = http_post_empty(ip, "/upgrade_query.html", timeout)
            pct = int(resp.strip())
        except (ValueError, RuntimeError):
            pct = -1

        elapsed = int(time.time() - start)
        if pct != last_pct:
            log(f"进度: {pct}% ({elapsed}s)")
            last_pct = pct

        if pct >= 100:
            return elapsed

        if elapsed > 600:
            raise RuntimeError(f"刷写超时 ({elapsed}s)，进度停在 {pct}%")

        time.sleep(POLL_INTERVAL)


def wait_reboot(ip: str, timeout: int) -> tuple[bool, int]:
    """等待 breed 消失（路由器重启），返回 (是否检测到重启, 等待秒数)。"""
    start = time.time()
    while time.time() - start < REBOOT_PROBE_TIMEOUT:
        time.sleep(REBOOT_PROBE_INTERVAL)
        elapsed = int(time.time() - start)
        try:
            status, headers, body = http_get(ip, "/", 5)
            server = headers.get("server", "")
            if "breed" not in server.lower():
                log(f"breed 已消失 ({elapsed}s) → 新系统已启动")
                return True, elapsed
            log(f"breed 仍在运行 ({elapsed}s)")
        except RuntimeError:
            log(f"连接断开 ({elapsed}s) → 路由器正在重启")
            return True, elapsed
    return False, int(time.time() - start)


# ============ 主流程 ============

def breed_flash(ip: str, filepath: str, timeout: int) -> dict:
    """执行完整刷机流程。"""
    if not os.path.isfile(filepath):
        raise RuntimeError(f"固件文件不存在: {filepath}")

    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    log(f"=== Breed 刷机开始 ===")
    log(f"固件: {os.path.basename(filepath)} ({file_size_mb:.1f}MB)")
    log(f"目标: {ip}")

    total_start = time.time()

    # 1. 上传
    log("=== 步骤 1/4: 上传固件 ===")
    upload_info = upload_firmware(ip, filepath, UPLOAD_TIMEOUT)
    log(f"上传确认: {upload_info.get('md5', '?')}")

    # 2. 触发刷写
    log("=== 步骤 2/4: 触发刷写 ===")
    trigger_flash(ip, timeout)

    # 3. 轮询进度
    log("=== 步骤 3/4: 轮询进度 ===")
    flash_sec = poll_progress(ip, timeout)
    log(f"刷写完成: {flash_sec}s")

    # 4. 等待重启
    log("=== 步骤 4/4: 等待重启 ===")
    reboot_ok, reboot_sec = wait_reboot(ip, timeout)

    total_sec = int(time.time() - total_start)

    result = {
        "ip": ip,
        "file": upload_info["filename"],
        "file_size": upload_info["file_size"],
        "md5": upload_info.get("md5"),
        "flash_duration_sec": flash_sec,
        "reboot_detected": reboot_ok,
        "reboot_wait_sec": reboot_sec,
        "total_duration_sec": total_sec,
    }

    if not reboot_ok:
        log("breed 仍在运行，可能需要手动重启", level="WARN")

    return result


# ============ CLI ============

def build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Breed Web 刷写固件（上传 + 触发 + 轮询 + 确认重启）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 刷写固件（默认 IP 192.168.1.1）\n"
            "  python3 5.breed_flash_firmware.py --file firmware.bin\n\n"
            "  # 指定 IP\n"
            "  python3 5.breed_flash_firmware.py "
            "--file firmware.bin --ip 192.168.1.1\n\n"
            "  # 查看参数 Schema\n"
            "  python3 5.breed_flash_firmware.py --help-json\n"
        ),
    )
    p.add_argument("--file", required=True,
                   help="固件文件路径（initramfs-kernel.bin）")
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP（默认: {DEFAULT_IP}）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
    return p


def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "Breed Web 刷写固件（上传 + 触发 + 轮询 + 确认重启）",
        "args": [
            {"name": "--file", "type": "string", "default": None,
             "required": True,
             "description": "固件文件路径（initramfs-kernel.bin）"},
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False,
             "description": f"路由器 IP（默认: {DEFAULT_IP}）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False,
             "description": f"HTTP 超时秒（默认: {DEFAULT_TIMEOUT}）"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印进度日志到 stderr（默认静默）"},
        ],
        "examples": [
            "python3 5.breed_flash_firmware.py --file firmware.bin",
            "python3 5.breed_flash_firmware.py "
            "--file firmware.bin --ip 192.168.1.1 --debug",
        ],
        "stdin_contract": {
            "expects": "无",
            "produces": "含 file/md5/flash_duration_sec/reboot_detected "
                        "的成功 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main() -> int:
    global DEBUG

    if "--help-json" in sys.argv:
        help_json_schema()
        return 0

    args = build_argparse().parse_args()
    DEBUG = args.debug

    if not os.path.isfile(args.file):
        emit_err(f"固件文件不存在: {args.file}",
                 reason="file_not_found", recoverable=True)
        return 1

    try:
        data = breed_flash(args.ip, args.file, args.timeout)
    except RuntimeError as e:
        msg = str(e)
        log(msg, level="ERROR")
        if "连接失败" in msg or "unreachable" in msg:
            emit_err(msg, reason="network_unreachable", recoverable=True)
            return 3
        emit_err(msg, reason="firmware_rejected", recoverable=False)
        return 1
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), recoverable=False)
        return 1

    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
