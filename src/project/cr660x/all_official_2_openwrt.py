#!/usr/bin/env python3
# cr660x/all_official_2_openwrt.py — CR660X 官方固件 → OpenWrt 全自动刷机
#
# 适用机型: CR6606(联通) / CR6608(移动) / CR6609(电信) / TR606/608/609
#          硬件相同 MT7621A, 仅运营商固件不同
#
# 流程:
#   扫 IP → init_info → variant 判定
#   ├─ 联通: try 12345678 → 失败→恢复出厂
#   ├─ 移动电信: 交互输入 8 位密码 → 2 次机会 → 恢复出厂
#   login → stok → 开 SSH (extendwifi→smartcontroller 双路)
#   → 上传 pb-boot → mtd write → 上传 initramfs → sysupgrade
#   → 等 OpenWrt → scp 正式固件 → sysupgrade → 完成
#
# 输出: stdout=单个 JSON, stderr=--debug 时日志

import argparse
import configparser
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_NAME = "all_official_2_openwrt"
DEBUG = False

# ============ 常量 ============
SCAN_IPS = ["192.168.2.1", "192.168.10.1", "192.168.31.1"]
INIT_INFO_URL = "http://{}/cgi-bin/luci/api/xqsystem/init_info"
INIT_INFO_TIMEOUT = 5
REBOOT_WAIT_TIMEOUT = 120
OPENWRT_WAIT_TIMEOUT = 180

DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "all_official_2_openwrt.ini")

UNICOM_SALT_R1D = "A2E371B0-B34B-48A5-8C40-A7133F3B5D88"
_UNICOM_SALT_OTHERS = "-".join(
    "d44fb0960aa0-a5e6-4a30-250f-6d2df50a".split("-")[::-1])


# ============ 日志 / 输出 ============

def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))


def emit_err(error: str, reason: str = "unknown", recoverable: bool = True,
             failed_step: str = "", steps_done: list = None) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "reason": reason, "failed_step": failed_step,
           "steps_done": steps_done or [], "recoverable": recoverable}
    print(json.dumps(out, ensure_ascii=False))


def worker_msg(msg: str) -> None:
    """打印给工人看的信息 (走 stderr, 不影响 JSON stdout)。"""
    print(f"[工人] {msg}", file=sys.stderr)


# ============ 配置读取 ============

def read_config(path: str) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    result = {}
    for section in cfg.sections():
        for key, val in cfg[section].items():
            result[f"{section}.{key}"] = val
    return result


# ============ 网络/等待工具 ============

def ping_host(ip: str, timeout: int = 2) -> bool:
    try:
        subprocess.run(["ping", "-c", "1", "-W", str(timeout), ip],
                       capture_output=True, timeout=timeout + 2, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def wait_ping_down(ip: str, timeout: int = 60) -> bool:
    log(f"等待 {ip} 离线 (timeout={timeout}s)...")
    for i in range(timeout):
        if not ping_host(ip, 1):
            log(f"{ip} 已离线 (≈{i}s)")
            return True
        time.sleep(1)
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
    return False


def wait_port_open(ip: str, port: int, timeout: int = 90) -> bool:
    log(f"等待 {ip}:{port} (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            return True
        except (OSError, ConnectionRefusedError, socket.timeout):
            time.sleep(2)
    return False


def fetch_init_info(ip: str) -> dict:
    url = INIT_INFO_URL.format(ip)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=INIT_INFO_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"获取 init_info 失败: {e}")


# ============ 密码工具 ============

def calc_unicom_root_password(sn: str) -> str:
    """联通版 SSH root 密码 = MD5(SN + salt)[:8]"""
    if not sn:
        return ""
    salt = _UNICOM_SALT_OTHERS if "/" in sn else UNICOM_SALT_R1D
    return hashlib.md5((sn + salt).encode()).hexdigest()[:8]


def validate_password(pwd: str) -> bool:
    """密码 8 位, 允许字母数字 ! @ #"""
    return bool(re.fullmatch(r"[A-Za-z0-9!@#]{8}", pwd))


# ============ subprocess 调用 ============

def run_script(cmd: list, label: str) -> dict:
    log(f"[{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"{label} 无输出 (exit={result.returncode}): {result.stderr[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} 非 JSON: {stdout[:200]}") from e
    if not data.get("ok"):
        raise RuntimeError(
            f"{label} 失败: {data.get('error', 'unknown')}"
            + (f" (reason: {data.get('reason', '')})" if data.get('reason') else ""))
    return data.get("data", {})


def run_shell_script(script_name: str, args: list, label: str) -> dict:
    cmd = [os.path.join(SCRIPT_DIR, script_name)] + args
    log(f"[{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if DEBUG and result.stderr:
        for line in result.stderr.strip().splitlines():
            log(f"[{label}] {line}")
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"{label} 无输出 (exit={result.returncode}): {result.stderr[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} 非 JSON: {stdout[:200]}") from e
    if isinstance(data, list):
        for item in data:
            if not item.get("ok"):
                raise RuntimeError(f"{label} 命令失败: {item.get('stderr', item.get('cmd'))}")
        return data[0] if data else {}
    if not data.get("ok"):
        raise RuntimeError(f"{label} 失败: {data.get('error', 'unknown')}")
    return data.get("data", {k: v for k, v in data.items() if k != "ok"})


# ============ 交互: 密码输入 (移动/电信) ============

def interact_password() -> str:
    """交互式获取 8 位贴纸密码, 允许字母数字 ! @ #, 最多 2 次"""
    for attempt in range(1, 3):
        raw = input(f"请输入路由器贴纸上的 8 位无线密码 (第 {attempt}/2 次): ").strip()
        if not validate_password(raw):
            print(f"密码必须恰好 8 位, 只允许字母/数字/!@#, 你输了 {len(raw)} 位")
            continue
        return raw
    raise RuntimeError("密码输入 2 次均不符合要求")


# ============ 交互: 恢复出厂 + 重试 ============

def prompt_factory_reset() -> bool:
    """提示工人恢复出厂, 返回 True=继续 False=放弃"""
    worker_msg("=" * 50)
    worker_msg("请按住路由器 RESET 孔 5-10 秒恢复出厂设置")
    worker_msg("等路由器重启完成后再继续")
    worker_msg("=" * 50)
    resp = input("恢复出厂后输入 yes 继续, 输入 skip 跳过此台 (yes/skip): ").strip().lower()
    return resp == "yes"


# ============ 主流程 ============

def main() -> int:
    global DEBUG

    if "--help-json" in sys.argv:
        help_json_schema()
        return 0

    # ============ 解析参数 ============
    p = argparse.ArgumentParser(
        description="CR660X 官方固件 → OpenWrt 全自动刷机",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 all_official_2_openwrt.py\n  python3 all_official_2_openwrt.py --debug",
    )
    p.add_argument("--pwd", default="",
                   help="管理密码 (不传则交互输入)")
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help=f"INI 配置 (默认: {DEFAULT_CONFIG})")
    p.add_argument("--ip", default="",
                   help="路由器 IP (不传则自动扫描)")
    p.add_argument("--extendwifi-ssid", default="",
                   help=f"HAKU 容器 SSID (覆盖 INI; 默认: 生产=socket.gethostname(), 调试=INI 配置)")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    DEBUG = args.debug

    cfg = read_config(args.config)
    if args.extendwifi_ssid:
        extendwifi_ssid = args.extendwifi_ssid
    else:
        ssid_debug = cfg.get("ssh.ssid_debug", "false").strip().lower() in ("true", "1", "yes")
        if ssid_debug:
            extendwifi_ssid = cfg.get("ssh.extendwifi_ssid", "HAKU-17")
        else:
            extendwifi_ssid = socket.gethostname()
    openwrt_ip = cfg.get("network.openwrt_ip", "192.168.1.1").strip()
    reboot_wait = int(cfg.get("network.reboot_wait", "120"))
    ssh_wait_timeout = int(cfg.get("ssh.ssh_wait_timeout", "90"))
    enable_ssh_retry = int(cfg.get("ssh.enable_ssh_retry", "3"))

    # 固件路径
    pb_boot = cfg.get("firmware.pb_boot_file", "")
    initramfs = cfg.get("firmware.initramfs_file", "")
    sysupgrade = cfg.get("firmware.sysupgrade_file", "")
    for key in ("pb_boot", "initramfs", "sysupgrade"):
        val = locals()[key]
        if val:
            locals()[key] = val if os.path.isabs(val) else os.path.join(SCRIPT_DIR, val)

    steps_done = []
    total_start = time.time()
    ip = args.ip

    try:
        # ============ 阶段 0: 扫 IP ============
        log("=== 阶段 0: 探测在线 IP ===")
        if not ip:
            results = run_shell_script("check_cr660x_ip_online.sh", [], "scan_ip")
            ip = results.get("found_ip", "")
            if not ip:
                raise RuntimeError("三个默认 IP 均无响应, 请确认路由器已上电并接入网络")
        else:
            if not ping_host(ip, 3):
                raise RuntimeError(f"路由器 {ip} 不可达")
        log(f"路由器在线: {ip}")
        steps_done.append("ip_found")

        # ============ 阶段 1: 获取路由器信息 ============
        log("=== 阶段 1: 获取路由器信息 ===")
        model = ""
        variant = ""
        inited = None
        romversion = ""
        try:
            info = fetch_init_info(ip)
            model = info.get("model", "").lower()
            hardware = info.get("hardware", "").lower()
            inited = info.get("inited")
            romversion = info.get("romversion", "")
            log(f"model={model} hardware={hardware} inited={inited} ver={romversion}")
        except Exception as e:
            log(f"init_info 不可用: {e} (部分 CR6609 没有此 API)")
            worker_msg("无法获取路由器信息 (init_info API 不可用)")

        if "cr6606" in model:
            variant = "unicom"
        elif "cr6608" in model or "cr6609" in model:
            variant = "move"
        else:
            # init_info 不可用或未知 model → 让工人选
            if not variant:
                worker_msg("无法自动识别运营商版本")
                print("  1) 联通 (CR6606 / TR606)")
                print("  2) 移动/电信 (CR6608 / CR6609 / TR608 / TR609)")
                v = input("请选择 [1/2], 默认 2: ").strip()
                variant = "unicom" if v == "1" else "move"
                if inited is None:
                    worker_msg("是否已初始化 (inited=0/1, 默认 0=工厂态)?")
                    inp = input("inited (0/1): ").strip()
                    inited = 1 if inp == "1" else 0
                worker_msg(f"按 {variant} 版流程, inited={inited}")
        log(f"variant={variant}")
        steps_done.append("variant_detected")

        # ============ 阶段 2: 获取管理密码 ============
        log("=== 阶段 2: 获取管理密码 ===")
        pwd = args.pwd
        if variant == "unicom":
            if not pwd:
                pwd = "12345678"
                log("联通版, 尝试默认密码 12345678")
            if inited == 1:
                log("inited=1, 尝试登录...")
                # 试密码
                try:
                    login_data = run_script(
                        [sys.executable,
                         os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
                         "--ip", ip, "--pwd", pwd],
                        "2.login_get_stok (12345678)"
                    )
                    stok = login_data.get("stok", "")
                    if stok:
                        log("12345678 登录成功!")
                        _skip_init = True
                except RuntimeError:
                    if not prompt_factory_reset():
                        raise RuntimeError("工人跳过此台, 标记为待处理")
                    steps_done.append("factory_reset")
                    # 等路由器重启
                    if not wait_ping_up(ip, REBOOT_WAIT_TIMEOUT):
                        raise RuntimeError("恢复出厂后等待上线超时")
                    inited = 0
        else:
            # 移动/电信: 需要 8 位贴纸密码
            if not pwd:
                pwd = interact_password()
            log(f"移动/电信版, 密码已获取")
        steps_done.append("password_obtained")

        # ============ 阶段 3: 初始化 + 登录 ============
        log("=== 阶段 3: 初始化 + 登录 ===")
        stok = ""
        if inited == 0:
            log("工厂态, 执行 1.official_init")
            init_data = run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "1.official_init.py"),
                 "--ip", ip, "--admin-pwd", pwd],
                "1.official_init"
            )
            steps_done.append("1.official_init")

        # 登录拿 stok
        login_data = run_script(
            [sys.executable,
             os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
             "--ip", ip, "--pwd", pwd],
            "2.login_get_stok"
        )
        stok = login_data.get("stok", "")
        if not stok:
            raise RuntimeError("登录成功但未获取 stok")
        steps_done.append("2.login_get_stok")

        # ============ 阶段 4: 双路 SSH 启用 ============
        log("=== 阶段 4: 启用 SSH ===")
        # SSH 启用后密码固定为 root (extendwifi token 里已 passwd root)
        ssh_pwd = "root"
        log(f"SSH 密码: {ssh_pwd}")

        ssh_ok = False
        defect_count = 0
        max_defect = 3

        while not ssh_ok and defect_count < max_defect:
            # 主路: extendwifi
            for attempt in range(1, enable_ssh_retry + 1):
                try:
                    log(f"extendwifi 开 SSH (尝试 {attempt}/{enable_ssh_retry})...")
                    run_script(
                        [sys.executable,
                         os.path.join(SCRIPT_DIR, "3.enable_ssh.py"),
                         "--ip", ip, "--stok", stok,
                         "--extendwifi-ssid", extendwifi_ssid],
                        "3.enable_ssh"
                    )
                    if wait_port_open(ip, 22, 30):
                        ssh_ok = True
                        break
                except RuntimeError as e:
                    log(f"extendwifi 第 {attempt} 次失败: {e}")
                time.sleep(5)
            if ssh_ok:
                break

            # 备路: smartcontroller
            try:
                log("extendwifi 都失败, 尝试 smartcontroller...")
                run_script(
                    [sys.executable,
                     os.path.join(SCRIPT_DIR, "enable_ssh_2.py"),
                     "--ip", ip, "--stok", stok],
                    "enable_ssh_2"
                )
                if wait_port_open(ip, 22, 60):
                    ssh_ok = True
                    break
            except RuntimeError as e:
                log(f"smartcontroller 失败: {e}")

            # 都失败 → 恢复出厂 + 重试
            defect_count += 1
            worker_msg(f"SSH 启用失败 (第 {defect_count}/{max_defect} 次)")
            if defect_count >= max_defect:
                raise RuntimeError(
                    f"SSH 启用失败 {max_defect} 次, 标记为废品需人工介入")
            if not prompt_factory_reset():
                raise RuntimeError("工人跳过此台, 标记为待处理")
            steps_done.append(f"factory_reset_ssh_{defect_count}")
            # 等路由器恢复
            if not wait_ping_up(ip, REBOOT_WAIT_TIMEOUT):
                raise RuntimeError("等待 SSH 故障恢复超时")
            # 重新初始化 + 登录
            try:
                info = fetch_init_info(ip)
                inited = info.get("inited", 0)
            except Exception:
                inited = 0
            if inited == 0:
                run_script(
                    [sys.executable,
                     os.path.join(SCRIPT_DIR, "1.official_init.py"),
                     "--ip", ip, "--admin-pwd", pwd],
                    "1.official_init (re-init)"
                )
            login_data = run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "2.login_get_stok.py"),
                 "--ip", ip, "--pwd", pwd],
                "2.login_get_stok (re-login)"
            )
            stok = login_data.get("stok", "")

        if not ssh_ok:
            raise RuntimeError("SSH 启用全部失败")

        steps_done.append("4.enable_ssh")
        log("SSH 已启用, 验证连接...")

        # 验证 SSH 连接
        run_shell_script("miwifi_ssh.sh",
                         ["--ip", ip, "--pwd", ssh_pwd, "--cmd", "echo OK"],
                         "ssh_verify")

        # ============ 阶段 5: 上传 pb-boot + mtd write ============
        log("=== 阶段 5: 写 pb-boot ===")
        if pb_boot and os.path.isfile(pb_boot):
            run_shell_script("4.firmware_upload_on_miwifi.sh",
                             ["--ip", ip, "--ssh-pwd", ssh_pwd,
                              "--file", pb_boot, "--target-name", "pb-boot.img"],
                             "upload_pb_boot")
            run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "5.uboot_write_in_miwifi.py"),
                 "--ip", ip, "--ssh-pwd", ssh_pwd, "--file", "pb-boot.img"],
                "5.uboot_write_in_miwifi"
            )
            steps_done.append("5.uboot_write")
        else:
            log(f"pb-boot 未配置或不存在 ({pb_boot}), 跳过")

        # ============ 阶段 6: 上传 initramfs + sysupgrade ============
        log("=== 阶段 6: sysupgrade initramfs ===")
        if initramfs and os.path.isfile(initramfs):
            run_shell_script("4.firmware_upload_on_miwifi.sh",
                             ["--ip", ip, "--ssh-pwd", ssh_pwd,
                              "--file", initramfs,
                              "--target-name", "initramfs-kernel.bin"],
                             "upload_initramfs")
            run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "6.openwrt_write_in_miwifi.py"),
                 "--ip", ip, "--ssh-pwd", ssh_pwd,
                 "--file", "initramfs-kernel.bin"],
                "6.openwrt_write_in_miwifi"
            )
            steps_done.append("6.sysupgrade_initramfs")
        else:
            log(f"initramfs 未配置或不存在 ({initramfs}), 跳过")

        # ============ 阶段 7: 等 OpenWrt + 烧正式固件 ============
        log("=== 阶段 7: 等路由器重启进 initramfs OpenWrt ===")
        # 先等旧 IP 离线（sysupgrade 触发重启）
        log(f"等待旧 IP {ip} 离线...")
        if wait_ping_down(ip, 30):
            log("旧 IP 已离线, 等待新 IP 上线...")
        else:
            log("旧 IP 未离线 (可能是同网段), 直接等新 IP...")

        log(f"调用 initramfs_2_standard.py (等 {openwrt_ip} → sysupgrade) ===")
        if sysupgrade and os.path.isfile(sysupgrade):
            data = run_script(
                [sys.executable,
                 os.path.join(SCRIPT_DIR, "initramfs_2_standard.py"),
                 "--ip", openwrt_ip,
                 "--ssh-pwd", ssh_pwd,
                 "--file", sysupgrade],
                "initramfs_2_standard"
            )
            steps_done.append("openwrt_online")
            steps_done.append("7.sysupgrade_final")
            # 验证 reboot 触发成功: 等 192.168.1.1 离线下线
            log(f"sysupgrade 已触发, 等待 {openwrt_ip} 离线确认刷写完成...")
            if wait_ping_down(openwrt_ip, 60):
                log(f"{openwrt_ip} 已离线, 刷写完成!")
            else:
                log(f"{openwrt_ip} 60s 内未离线 (可能同 IP 启动), 继续")
        else:
            log(f"sysupgrade 固件未配置或不存在 ({sysupgrade}), 跳过 openwrt 阶段")
            log("路由器在 initramfs 中, 可手动 sysupgrade")

        total_sec = round(time.time() - total_start, 1)
        emit_ok({
            "ip": ip, "variant": variant, "target": "openwrt",
            "firmware": os.path.basename(sysupgrade) if sysupgrade else "none",
            "steps": steps_done,
            "total_duration_sec": total_sec,
        })
        return 0

    except RuntimeError as e:
        failed_step = steps_done[-1] if steps_done else "pre_check"
        emit_err(str(e), failed_step=failed_step, steps_done=steps_done)
        return 1
    except Exception as e:
        emit_err(str(e), failed_step=steps_done[-1] if steps_done else "pre_check",
                 steps_done=steps_done)
        return 1


# ============ help-json ============

def help_json_schema() -> None:
    schema = {
        "script": STEP_NAME,
        "description": "CR660X 官方固件 → OpenWrt 全自动刷机",
        "args": [
            {"name": "--pwd", "type": "string", "default": "",
             "required": False,
             "description": "管理密码 (不传则交互输入; 联通版默认 12345678)"},
            {"name": "--config", "type": "file", "default": DEFAULT_CONFIG,
             "required": False, "description": "INI 配置"},
            {"name": "--ip", "type": "string", "default": "",
             "required": False, "description": "路由器 IP (不传则自动扫描)"},
            {"name": "--extendwifi-ssid", "type": "string", "default": "",
             "required": False, "description": "HAKU 容器 SSID"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False, "description": "打印进度日志"},
        ],
        "pipeline": [
            "scan_ip", "get_router_info", "variant_detect",
            "password_input (move) / auto (unicom)",
            "1.official_init (if factory)", "2.login_get_stok",
            "3.enable_ssh (extendwifi) → fallback enable_ssh_2 (smartcontroller)",
            "4.upload_pb_boot → 5.mtd_write",
            "4.upload_initramfs → 6.sysupgrade_initramfs",
            "wait_openwrt → 7.sysupgrade_final",
        ],
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
