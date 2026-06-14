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

import json
import os
import subprocess
import sys
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
        print()
        print("  0. 退出")
        print()

        try:
            choice = input("  请选择 [0-2]: ").strip()
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
        else:
            print("无效选项")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n退出")
        sys.exit(0)
