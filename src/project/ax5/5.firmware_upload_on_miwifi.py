#!/usr/bin/env python3
# 5.firmware_upload_on_miwifi.py — scp 上传固件到路由器 /tmp/
# 适用机型: Redmi AX5 (RA67 / RM1800) — IPQ6000
#
# 走 sshpass + scp -O 强制 legacy SCP 协议 (Dropbear 旧版不支持 sftp)
# 加 -oHostKeyAlgorithms=+ssh-rsa (路由器只支持 ssh-rsa 旧算法)
# 加 -oStrictHostKeyChecking=no + -oUserKnownHostsFile=/dev/null
#   → 免掉 host key 首次连接的交互 prompt
#
# ⚠️  与 miwifi_ssh.sh 不同: 本脚本走 scp (非交互式文件传输),
#     不走 SSH exec 通道 (miwifi_ssh.sh 是 SSH 命令模式, 不支持文件传输)
#
# 流程:
#   1. 验证 --file 存在
#   2. 检查 sshpass 依赖
#   3. sshpass + scp -O 推到 root@<ip>:/tmp/<target>
#   4. 输出 JSON
#
# 使用:
#   ./5.firmware_upload_on_miwifi.py --file files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi
#   ./5.firmware_upload_on_miwifi.py --file files/openwrt.ubi --target-name custom.ubi
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": "firmware_upload_on_miwifi", "data"|"error": ...}
#       stderr = 默认静默, --debug 保留
#       exit  = 0 成功 / 1 失败 / 2 参数错误 / 5 超时
#
# 依赖: sshpass  (apt install sshpass / apk add sshpass)

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

STEP_NAME = "firmware_upload_on_miwifi"
DEFAULT_IP = "192.168.31.1"
DEFAULT_SSH_PWD = "root"
DEFAULT_TIMEOUT = 60

# 过滤掉的 stderr 行 (ssh host key 首次连接 warning)
FILTER_PATTERNS = (
    "Warning: Permanently added",
    "Warning: 'ssh-rsa' host key",
)


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO", debug: bool = False) -> None:
    if not debug:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps(
        {"ok": True, "step": STEP_NAME, "data": data},
        ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {
        "ok": False,
        "step": STEP_NAME,
        "error": error,
        "recoverable": recoverable,
    }
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ 依赖检查 ============
def check_dep(tool: str) -> str | None:
    if shutil.which(tool) is None:
        return f"依赖缺失: {tool} (apt install {tool})"
    return None


# ============ scp 上传 ============
def scp_upload(file: str, target: str, ip: str, ssh_pwd: str,
               debug: bool = False, timeout: int = DEFAULT_TIMEOUT) -> tuple:
    """scp 上传, 返回 (ok, error_msg)"""
    remote = f"root@{ip}:/tmp/{target}"
    cmd = [
        "sshpass", "-p", ssh_pwd, "scp", "-O",
        "-oHostKeyAlgorithms=+ssh-rsa",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        file, remote,
    ]
    log(f"exec: {' '.join(cmd)}", debug=debug)

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"scp 超时 ({timeout}s)"
    except FileNotFoundError as e:
        return False, f"命令未找到: {e}"

    # stderr: debug 全部透传; 默认过滤 host key warning, 保留 scp 进度条
    if p.stderr:
        for line in p.stderr.splitlines(keepends=True):
            if debug or not any(pat in line for pat in FILTER_PATTERNS):
                sys.stderr.write(line)
        sys.stderr.flush()

    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-3:]
        err_text = "\n".join(tail) if tail else "scp 失败"
        return False, f"scp 失败 (exit {p.returncode}): {err_text[:400]}"

    return True, None


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "scp 上传固件到路由器 /tmp/ (Dropbear 旧版走 legacy SCP)",
        "args": [
            {"name": "--file", "type": "string", "default": None,
             "required": True, "description": "本地文件路径"},
            {"name": "--ip", "type": "string", "default": DEFAULT_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--target-name", "type": "string", "default": None,
             "required": False,
             "description": "/tmp/ 下的目标文件名, 默认 <file> 的 basename"},
            {"name": "--ssh-pwd", "type": "string", "default": DEFAULT_SSH_PWD,
             "required": False, "description": "SSH 密码"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "保留所有 stderr (host key warning 等)"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
        ],
        "examples": [
            "./5.firmware_upload_on_miwifi.py --file files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi",
            "./5.firmware_upload_on_miwifi.py --file files/openwrt.ubi --target-name custom.ubi",
        ],
        "stdin_contract": {
            "expects": "无 (本脚本不接受 stdin JSON)",
            "produces": "成功: {ok:true, data:{ip, file, target, remote_path, next_step}}",
        },
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="scp 上传固件到路由器 /tmp/ (Dropbear 旧版走 legacy SCP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 基础用法 (默认推到 192.168.31.1 的 /tmp/<basename>)\n"
            "  ./5.firmware_upload_on_miwifi.py --file files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi\n"
            "\n"
            "  # 自定义目标文件名\n"
            "  ./5.firmware_upload_on_miwifi.py --file files/openwrt.ubi --target-name custom.ubi\n"
            "\n"
            "  # 跑完后建议:\n"
            "  # 1) 验证上传成功: ./miwifi_ssh.sh --cmd 'ls -la /tmp/<target>'\n"
            "  # 2) 烧到对侧 mtd:  python3 6.miwifi_2_openwrt.py --file-name <target>"
        ),
    )
    p.add_argument("--file", required=True, help="本地文件路径 (必传)")
    p.add_argument("--ip", default=DEFAULT_IP,
                   help=f"路由器 IP (默认: {DEFAULT_IP})")
    p.add_argument("--target-name", default=None,
                   help="/tmp/ 下的目标文件名, 默认 <file> 的 basename")
    p.add_argument("--ssh-pwd", default=DEFAULT_SSH_PWD,
                   help=f"SSH 密码 (默认: {DEFAULT_SSH_PWD})")
    p.add_argument("--debug", action="store_true",
                   help="详细日志 (默认静默)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒 (默认: {DEFAULT_TIMEOUT})")
    return p.parse_args()


def main() -> int:
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    debug = args.debug

    if not args.file:
        emit_err("--file 必传", reason="missing_arg")
        return 2
    if not os.path.isfile(args.file):
        emit_err(f"文件不存在: {args.file}", reason="file_not_found")
        return 2

    target = args.target_name if args.target_name else os.path.basename(args.file)
    log(f"参数: ip={args.ip} file={args.file} target={target}", debug=debug)

    for tool in ("sshpass", "scp"):
        err = check_dep(tool)
        if err:
            emit_err(err, reason="dep_missing", recoverable=False)
            return 1

    ok, err = scp_upload(args.file, target, args.ip, args.ssh_pwd,
                         debug=debug, timeout=args.timeout)
    if not ok:
        reason = "scp_timeout" if "超时" in (err or "") else "scp_failed"
        emit_err(err, reason=reason, recoverable=True)
        return 5 if "超时" in (err or "") else 1

    log("scp 完成", debug=debug)
    emit_ok({
        "ip": args.ip,
        "file": os.path.abspath(args.file),
        "target": target,
        "remote_path": f"/tmp/{target}",
        "next_step": (
            f"python3 6.miwifi_2_openwrt.py --file-name {target}"
        ),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
