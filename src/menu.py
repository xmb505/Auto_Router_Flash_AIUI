#!/usr/bin/env python3
# menu.py — 统一刷机入口菜单
#
# 用法:
#   python3 src/menu.py
#
# 选项:
#   1) 新路由 (Newifi D2)
#      └─ 二级子菜单: 官方to breed / breed to OpenWrt
#   2) 小米官方版本 (AX5/AX6/AX3600/AX3000T)
#      └─ 自动 ping 检测 → 读取硬件型号 → 匹配脚本 → 开始刷机
#   3) CR660X 系列 (联通/移动/电信)
#      └─ 实时 IP 探测 + 全流程 / pb-boot 子菜单

import configparser
import json
import os
import select
import subprocess
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "project")
MIWIFI_UTILS = os.path.join(SCRIPT_DIR, "miwifi_official_utils")

# 硬件型号 → 机型目录映射（全小写匹配）
HARDWARE_MAP = {
    "ra67":  "ax5",
    "ra69":  "ax6",
    "r3600": "ax3600",
    "rd03":  "ax3000t",
}


# ============ 工具函数 ============

def clear_screen():
    os.system("clear" if os.name == "posix" else "cls")


def pause(msg: str = ""):
    """显示提示并按回车继续"""
    if msg:
        print(msg)
    input("按 Enter 键返回菜单...")


def run_with_debug(cmd: list, cwd: str, label: str) -> bool:
    """运行命令并捕获结果，异常时提示回车返回"""
    print(f"\n{'='*60}")
    print(f"  运行: {label}")
    print(f"  命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    try:
        result = subprocess.run(cmd, cwd=cwd, timeout=1800)
        if result.returncode != 0:
            print(f"\n⚠️ 脚本异常退出 (exit code={result.returncode})")
            pause()
            return False
        print(f"\n✅ {label} 完成")
        return True
    except subprocess.TimeoutExpired:
        print("\n⚠️ 脚本超时 (30 分钟)")
        pause()
        return False
    except FileNotFoundError as e:
        print(f"\n⚠️ 找不到脚本: {e}")
        pause()
        return False
    except Exception as e:
        print(f"\n⚠️ 运行出错: {e}")
        pause()
        return False


def get_hardware_info() -> dict:
    """调用 get_router_info.sh 获取硬件信息"""
    script = os.path.join(MIWIFI_UTILS, "get_router_info.sh")
    if not os.path.isfile(script):
        return {}
    try:
        result = subprocess.run(
            ["bash", script, "--ip", "192.168.31.1"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        return data
    except Exception:
        return {}


def find_model_dir(hardware: str) -> str:
    """根据 hardware 字段匹配机型目录"""
    key = hardware.strip().lower()
    model = HARDWARE_MAP.get(key)
    if model:
        return os.path.join(PROJECT_DIR, model)
    return ""


def get_script_path(model_dir: str) -> str:
    """返回 all_official_2_openwrt.py 路径"""
    script = os.path.join(model_dir, "all_official_2_openwrt.py")
    return script if os.path.isfile(script) else ""


# ============ CR660X IP 探测 ============

CR_IPS = ["192.168.1.1", "192.168.2.1", "10.11.12.1",
          "192.168.10.1", "192.168.31.1"]

IP_LABELS = {
    "192.168.1.1":   "pb-boot",
    "192.168.2.1":   "电信",
    "10.11.12.1":    "客户固件",
    "192.168.10.1":  "移动",
    "192.168.31.1":  "联通/小米/电信",
}


def _ping_one(ip: str, results: dict, lock: threading.Lock):
    """单个 IP ping 检测（后台线程用）"""
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True, timeout=4,
        )
        online = r.returncode == 0
    except Exception:
        online = False
    with lock:
        results[ip] = online


def probe_ips() -> dict:
    """并行 ping 全部 CR IP，返回 {ip: bool}"""
    results = {}
    lock = threading.Lock()
    threads = []
    for ip in CR_IPS:
        t = threading.Thread(target=_ping_one, args=(ip, results, lock), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=6)
    for ip in CR_IPS:
        results.setdefault(ip, False)
    return results


def render_ip_status(results: dict) -> list:
    """渲染 IP 状态行，返回 [str, ...]"""
    lines = []
    online_any = False
    for ip in CR_IPS:
        ok = results.get(ip, False)
        label = IP_LABELS.get(ip, "")
        if ok:
            lines.append(f"    \033[32m● {ip}\033[0m  {label}")
            online_any = True
        else:
            lines.append(f"    \033[31m○ {ip}\033[0m  {label}")
    if not online_any:
        lines.append("    \033[33m（所有 IP 均离线，请检查网线连接）\033[0m")
    return lines


def _read_line_nonblocking(timeout_s: float) -> str | None:
    """带超时的非阻塞 stdin 读取（仅 Linux/macOS select）"""
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], timeout_s)
        if rlist:
            return sys.stdin.readline().strip()
    except Exception:
        pass
    return None


# ============ 小米刷机流程 ============

def xiaomi_flash():
    """小米官方版本自动刷机"""
    clear_screen()
    print("=== 小米官方版本刷机 ===")
    print()

    # 1. Ping 检测
    print("正在检测路由器 (192.168.31.1)...")
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "3", "192.168.31.1"],
                           capture_output=True, timeout=5)
        if r.returncode != 0:
            print("❌ 路由器 192.168.31.1 不可达（ping 超时）")
            print("  请检查网络连接，确保电脑 IP 在 192.168.31.x 网段")
            pause()
            return
    except Exception as e:
        print(f"❌ Ping 检测失败: {e}")
        pause()
        return
    print("✅ 路由器在线")

    # 2. 获取硬件信息
    print("正在获取路由器信息...")
    info = get_hardware_info()
    if not info:
        print("❌ 无法获取路由器信息（get_router_info.sh 无返回）")
        pause()
        return

    hardware = info.get("hardware", "")
    model_name = info.get("model", "")
    romversion = info.get("romversion", "")
    print(f"  型号: {model_name}")
    print(f"  硬件: {hardware}")
    print(f"  版本: {romversion}")

    # 3. 匹配机型
    model_dir = find_model_dir(hardware)
    if not model_dir:
        print(f"❌ 未识别的硬件型号: {hardware}")
        print(f"  支持的型号: {', '.join(HARDWARE_MAP.keys())}")
        pause()
        return

    script = get_script_path(model_dir)
    if not script:
        print(f"❌ {model_dir} 下没有 all_official_2_openwrt.py")
        pause()
        return

    model_label = os.path.basename(model_dir)
    print(f"\n✅ 匹配到机型: {model_label} ({hardware})")
    print(f"   脚本: {os.path.relpath(script, SCRIPT_DIR)}")
    print()

    # 4. 确认
    try:
        choice = input("  开始刷机？(Y/n): ").strip().lower()
        if choice == "n":
            print("已取消")
            pause()
            return
    except (EOFError, KeyboardInterrupt):
        print()
        return

    # 5. 运行编排器
    cmd = [sys.executable, script, "--debug"]
    run_with_debug(cmd, model_dir, f"{model_label} → OpenWrt")


# ============ CR660X 子菜单 ============

def cr660x_menu():
    """CR660X 二级子菜单（单行 IP 状态，每 5 秒刷新）"""
    cr660x_dir = os.path.join(PROJECT_DIR, "cr660x")

    def _format_status_line(results: dict) -> str:
        """单行：在线 IP 逗号分隔；全离线时显示提示"""
        online = [ip for ip in CR_IPS if results.get(ip)]
        if online:
            return f"\033[32m在线 IP:\033[0m {', '.join(online)}"
        return "\033[33m在线 IP: 无（请检查网线）\033[0m"

    def _draw_menu(results):
        """绘制完整菜单（含 IP 状态行），返回 (状态行距光标行数)"""
        clear_screen()
        print("=" * 40)
        print("      CR660X 系列刷机")
        print("=" * 40)
        print(f"  {_format_status_line(results)}")
        print()
        print("  1. 官方固件 → OpenWrt（全自动全流程）")
        print("  2. Pb-boot → OpenWrt（已刷 pb-boot，192.168.1.1 在线）")
        print()
        print("  0. 返回上级菜单")
        print()
        sys.stdout.write("  请选择 [0-2]: ")
        sys.stdout.flush()
        return 7  # 状态行距光标 7 行

    # 首次探测 + 绘制
    last_results = probe_ips()
    last_probe_time = time.monotonic()
    status_line_offset = _draw_menu(last_results)

    while True:
        choice = None
        while True:
            elapsed = time.monotonic() - last_probe_time
            wait = max(0.5, 5.0 - elapsed)
            line = _read_line_nonblocking(wait)
            if line is not None:
                choice = line
                break
            if time.monotonic() - last_probe_time >= 5.0:
                last_results = probe_ips()
                last_probe_time = time.monotonic()
                sys.stdout.write(f"\033[s\033[{status_line_offset}A\033[2K  {_format_status_line(last_results)}\033[u")
                sys.stdout.flush()

        if choice == "0":
            return
        elif choice == "1":
            script = os.path.join(cr660x_dir, "all_official_2_openwrt.py")
            if os.path.isfile(script):
                cmd = [sys.executable, script, "--debug"]
                run_with_debug(cmd, cr660x_dir, "CR660X 官方 → OpenWrt")
            else:
                print("❌ 找不到 all_official_2_openwrt.py")
                pause()
        elif choice == "2":
            script = os.path.join(cr660x_dir, "pandora_2_openwrt.py")
            if os.path.isfile(script):
                ini_path = os.path.join(cr660x_dir, "all_official_2_openwrt.ini")
                cfg = configparser.ConfigParser()
                cfg.read(ini_path)
                initramfs = cfg.get("firmware", "initramfs_file", fallback="files/initramfs-kernel.bin")
                sysupgrade = cfg.get("firmware", "sysupgrade_file", fallback="")
                cmd = [sys.executable, script, "--debug",
                       "--initramfs", os.path.join(cr660x_dir, initramfs)]
                if sysupgrade:
                    cmd.extend(["--sysupgrade", os.path.join(cr660x_dir, sysupgrade)])
                run_with_debug(cmd, cr660x_dir, "CR660X Pb-boot → OpenWrt")
            else:
                print("❌ 找不到 pandora_2_openwrt.py")
                pause()
        else:
            print("无效选项")
            time.sleep(1)

        # 选项返回后重绘菜单
        last_results = probe_ips()
        last_probe_time = time.monotonic()
        _draw_menu(last_results)


# ============ 新路由子菜单 ============

def newifi_menu():
    """新路由二级子菜单"""
    newifi_dir = os.path.join(PROJECT_DIR, "newifid2")
    while True:
        clear_screen()
        print("=== 新路由 (Newifi D2) 刷机 ===")
        print()
        print("  1. 官方固件 → Breed 注入")
        print("  2. Breed → OpenWrt 刷机")
        print("  0. 返回上级菜单")
        print()

        try:
            choice = input("  请选择 [0-2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0":
            break
        elif choice == "1":
            script = os.path.join(newifi_dir, "all_official_2_breed.py")
            if os.path.isfile(script):
                cmd = [sys.executable, script, "--debug"]
                run_with_debug(cmd, newifi_dir, "Newifi D2 官方 → Breed")
            else:
                print("❌ 找不到 all_official_2_breed.py")
                pause()
        elif choice == "2":
            script = os.path.join(newifi_dir, "all_breed_auto_flash.py")
            if os.path.isfile(script):
                cmd = [sys.executable, script, "--debug"]
                run_with_debug(cmd, newifi_dir, "Newifi D2 Breed → OpenWrt")
            else:
                print("❌ 找不到 all_breed_auto_flash.py")
                pause()
        else:
            print("无效选项")
            pause()


# ============ 主菜单 ============

def main_menu():
    while True:
        clear_screen()
        print("=" * 40)
        print("      Auto Router Flash AIUI")
        print("      路由器刷机统一入口")
        print("=" * 40)
        print()
        print("  1. 新路由 (Newifi D2)")
        print("  2. 小米官方版本 (自动检测机型)")
        print("  3. CR660X 系列 (联通/移动/电信)")
        print()
        print("  0. 退出")
        print()

        try:
            choice = input("  请选择 [0-3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0":
            print("退出")
            break
        elif choice == "1":
            newifi_menu()
        elif choice == "2":
            xiaomi_flash()
        elif choice == "3":
            cr660x_menu()
        else:
            print("无效选项")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n退出")
        sys.exit(0)
