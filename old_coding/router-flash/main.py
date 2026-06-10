#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由器刷机工具主程序

整合 UI 和刷机逻辑
"""

import os
import sys
import time
import tty
import termios
import select
import subprocess
import threading
import socket
import requests
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from config import config
from cr660x.flasher import CR660XFlasher
from jgc.flasher import JGCFlasher
from ax3000t.flasher import AX3000TFlasher
from ax3600.flasher import AX3600Flasher
from ax6.flasher import AX6Flasher
from ax5.flasher import AX5Flasher
from utils import NetworkTool, ShellTool

console = Console()

# 全局计数器
flash_count = 0
recorded_macs = set()

# 全局日志
flash_logs = []

# 全局 IP 检测状态（用于后台线程与 UI 通信）
jgc_online_ip = None
jgc_first_detect_done = False
jgc_detect_stop = threading.Event()
jgc_input_buffer = ""  # 用户输入缓冲区

# 跨阶段持久化存储（AX6 SSH密码等）
persist = {"ssh_password": None, "stok": None}


class Colors:
    GREEN = "green"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    WHITE = "white"
    CYAN = "cyan"
    DIM = "dim"


class Icons:
    SUCCESS = "✅"
    FAIL = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    LOADING = "⏳"


def clear_screen():
    os.system('clear')


def get_hostname():
    return os.uname().nodename


def input_str(prompt=""):
    return input(prompt).strip()


def show_start_screen():
    """开始界面"""
    clear_screen()

    console.print(Panel(
        Text("路由器刷机工具 v2.0", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    console.print(f"工作节点：{get_hostname()}", style=f"{Colors.WHITE}")
    console.print()
    console.print("请选择要刷机的路由器型号：", style=f"bold {Colors.WHITE}")
    console.print()
    console.print("[1] CR660X 小米/联通路由器", style=f"{Colors.WHITE}")
    console.print("[2] JGC Q10/Q20 路由器", style=f"{Colors.WHITE}")
    console.print("[3] AX3000T 小米路由器", style=f"{Colors.WHITE}")
    console.print("[4] AX3600 小米路由器", style=f"{Colors.WHITE}")
    console.print("[5] AX6 红米路由器", style=f"{Colors.WHITE}")
    console.print("[6] AX5 红米路由器", style=f"{Colors.WHITE}")
    console.print()
    console.print(Panel(
        Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    return input_str("请输入数字 [1-6]：")


def show_cr660x_main_screen():
    """CR660X 主菜单"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("CR660X/TR660X 批量刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        # 检测在线 IP（包括 192.168.1.1）
        detect_ips = config.cr660x.get('detect_ips', ['192.168.1.1', '192.168.10.1', '192.168.2.1'])
        ping_interval = config.global_settings.get('ping_interval', 1)
        online_ip = None
        for ip in detect_ips:
            if NetworkTool.ping(ip):
                online_ip = ip
                break
            time.sleep(ping_interval) if ping_interval > 0 else None

        if online_ip:
            console.print(f"在线路由器：{online_ip}", style=f"bold {Colors.GREEN}")
        else:
            console.print("未检测到路由器", style=f"bold {Colors.RED}")
        console.print()

        console.print("请选择刷机流程：", style=f"bold {Colors.WHITE}")
        console.print()
        console.print("[1] 官方系统破解刷入BOOTLOADER和KERNEL", style=f"{Colors.WHITE}")
        console.print("     └─ 刷入后自动进入第二阶段", style=f"dim {Colors.DIM}")
        console.print("[2] OPENWRT升级自定义固件", style=f"{Colors.WHITE}")
        console.print("     └─ 升级已有openwrt系统", style=f"dim {Colors.DIM}")
        console.print("[3] UBOOT上传KERNEL并升级", style=f"{Colors.WHITE}")
        console.print("     └─ 从uboot状态刷入kernel后自动升级", style=f"dim {Colors.DIM}")
        console.print()

        console.print(Panel(
            Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        console.print(Panel(
            Text("按 [r] 重新检测 IP | 按 [q] 返回主菜单", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        choice = input_str("你的选择是：")

        if choice == 'r' or choice == 'R':
            continue  # 重新循环检测 IP

        return choice, online_ip


def show_cr660x_carrier_screen():
    """选择运营商"""
    clear_screen()

    console.print(Panel(
        Text("CR660X/TR660X 批量刷机模式", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()

    console.print("所处模式：1 - 刷机模式", style=f"{Colors.WHITE}")
    console.print()
    console.print("请选择运营商：", style=f"bold {Colors.WHITE}")
    console.print()
    console.print("[1] 中国移动 / 中国电信", style=f"{Colors.WHITE}")
    console.print("     └─ 需要输入路由器密码", style=f"dim {Colors.DIM}")
    console.print("[2] 中国联通", style=f"{Colors.WHITE}")
    console.print("     └─ 恢复出厂设置，自动刷机", style=f"dim {Colors.DIM}")
    console.print()

    console.print(Panel(
        Text("提示：联通版本会恢复出厂设置，不需要密码", style=f"dim {Colors.YELLOW}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    console.print(Panel(
        Text("按 [q] 返回上一步", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    return input_str("请输入数字 [1-2]：")


def show_password_input_screen(ip="192.168.10.1"):
    """密码输入界面"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("CR660X/TR660X 批量刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        console.print("所处模式：1 - 刷机模式", style=f"{Colors.WHITE}")
        console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
        console.print()
        console.print(Text("💡 提示：密码在路由器背面贴纸上", style=f"dim {Colors.YELLOW}"))
        console.print()
        console.print(Panel(
            Text("按 [q] 返回上一步", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        password = input_str("请输入路由器管理密码：")

        if password == 'q' or password == 'Q':
            return password

        # 密码校验：必须为8位
        if len(password) != 8:
            console.print()
            console.print(Panel(
                Text(f"❌ 密码必须为8位，当前为 {len(password)} 位，请重新输入", style=f"bold {Colors.RED}"),
                border_style=f"{Colors.RED}"
            ))
            console.print()
            input("按 [Enter] 继续...")
            continue

        return password


def _jgc_detect_ips():
    """后台持续检测 IP 的线程函数"""
    global jgc_online_ip, jgc_first_detect_done, jgc_detect_stop

    detect_ips = config.jgc.get('detect_ips', {})
    jgc_ips = [
        detect_ips.get('official', '192.168.10.1'),
        detect_ips.get('official_qx', '192.168.2.1'),
        detect_ips.get('pdcn', '192.168.123.1'),
        detect_ips.get('uboot', '192.168.1.1'),
        detect_ips.get('final', '10.11.12.1'),
    ]
    ping_interval = config.global_settings.get('ping_interval', 1)

    while not jgc_detect_stop.is_set():
        try:
            for ip in jgc_ips:
                if jgc_detect_stop.is_set():
                    break
                if NetworkTool.ping(ip):
                    jgc_online_ip = ip
                    break
                time.sleep(ping_interval) if ping_interval > 0 else None
            else:
                # 所有 IP 都没检测到
                jgc_online_ip = None
        except Exception:
            # 忽略异常，继续下一轮检测
            pass

        # 第一轮检测完成
        jgc_first_detect_done = True

        # 等待一小段时间再继续下一轮检测
        time.sleep(1)


def _jgc_start_detect_thread():
    """启动后台 IP 检测线程"""
    global jgc_online_ip, jgc_first_detect_done, jgc_detect_stop

    jgc_detect_stop.clear()
    jgc_online_ip = None
    jgc_first_detect_done = False

    thread = threading.Thread(target=_jgc_detect_ips, daemon=True)
    thread.start()
    return thread


def _jgc_stop_detect_thread():
    """停止后台 IP 检测线程"""
    global jgc_detect_stop
    jgc_detect_stop.set()


def _jgc_build_menu(input_text=""):
    """构建 JGC 菜单面板（用于 Live 刷新）"""
    global jgc_online_ip, jgc_first_detect_done, flash_count

    if not jgc_first_detect_done:
        ip_line = "[bold yellow]正在检测IP...[/]"
    elif jgc_online_ip:
        ip_line = f"[bold green]在线路由器：{jgc_online_ip}[/]"
    else:
        ip_line = "[bold red]未检测到路由器[/]"

    # 输入提示和已输入的内容
    prompt_line = f"[bold white]请输入数字 [1-3]，按 [q] 返回: [/][cyan]{input_text}[/]"

    content = (
        f"\n{ip_line}\n\n"
        f"[bold white]请选择刷机步骤：[/]\n\n"
        f"[1] 步骤 1：官方→PDCN\n"
        f"     └─ [dim]更换路由器系统[/]\n"
        f"[2] 步骤 2：PDCN→引导程序\n"
        f"     └─ [dim]刷入启动引导[/]\n"
        f"[3] 步骤 3：引导→最终系统\n"
        f"     └─ [dim]刷入最终系统[/]\n\n"
        f"已成功刷入：{flash_count} 台\n\n"
        f"{prompt_line}\n\n"
        f"[dim]IP 自动检测中，检测到路由器将自动显示[/]"
    )

    return Panel(
        content,
        title="[bold cyan]JGC Q10/Q20 路由器刷机[/]",
        border_style="blue",
    )


def _jgc_input_thread(result_list, stop_event):
    """后台输入线程 - 逐字符读取"""
    global jgc_input_buffer
    jgc_input_buffer = ""

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        while not stop_event.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch == '\n' or ch == '\r':
                    # 回车，提交输入
                    result_list.append(jgc_input_buffer.strip())
                    break
                elif ch == '\x7f' or ch == '\x08':
                    # 退格
                    if jgc_input_buffer:
                        jgc_input_buffer = jgc_input_buffer[:-1]
                elif ch == '\x03':
                    # Ctrl+C
                    result_list.append('q')
                    break
                elif len(ch) == 1:
                    jgc_input_buffer += ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def show_jgc_menu_screen():
    """JGC 主菜单 - 自动刷新 IP"""
    global jgc_online_ip, jgc_first_detect_done, jgc_input_buffer

    # 启动后台 IP 检测线程
    detect_thread = _jgc_start_detect_thread()

    result = []
    input_stop = threading.Event()

    try:
        with Live(_jgc_build_menu(), console=console, refresh_per_second=4) as live:
            # 启动输入线程
            t = threading.Thread(target=_jgc_input_thread, args=(result, input_stop), daemon=True)
            t.start()

            # 等待输入结果，同时 Live 自动刷新显示
            while not result:
                time.sleep(0.25)
                live.update(_jgc_build_menu(jgc_input_buffer))

            choice = result[0]
            input_stop.set()

            if choice == 'q' or choice == 'Q':
                return 'q', None

            return choice, jgc_online_ip
    finally:
        input_stop.set()
        _jgc_stop_detect_thread()
        if detect_thread:
            detect_thread.join(timeout=2)


def show_jgc_password_screen(ip="192.168.10.1"):
    """JGC 密码输入界面"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("JGC Q10/Q20 路由器刷机", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
        console.print()
        console.print(Text("自动获取密码失败，请手动输入", style=f"bold {Colors.YELLOW}"))
        console.print()

        console.print(Panel(
            Text("按 [q] 返回上一步", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        password = input_str("请输入路由器管理密码：")

        if password == 'q' or password == 'Q':
            return password

        if not password:
            console.print()
            console.print(Panel(
                Text("密码不能为空，请重新输入", style=f"bold {Colors.RED}"),
                border_style=f"{Colors.RED}"
            ))
            console.print()
            input("按 [Enter] 继续...")
            continue

        return password


def show_success_screen(step="步骤 1/3", next_action="系统正在重启...",
                        show_count=False, auto_wait=0):
    """刷机成功完成"""
    clear_screen()

    console.print(Panel(
        Text(f"{Icons.SUCCESS} 刷机成功！", style=f"bold {Colors.GREEN}"),
        border_style=f"{Colors.GREEN}"
    ))
    console.print()

    console.print(f"已完成 {step}", style=f"{Colors.WHITE}")
    console.print()
    console.print("─" * 40)
    console.print()
    console.print(f"下一步：{next_action}", style=f"{Colors.WHITE}")
    console.print(Text(f"{Icons.LOADING} 正在继续，请稍候...", style=f"{Colors.YELLOW}"))
    console.print()

    if show_count:
        console.print(Panel(
            Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

    if auto_wait > 0:
        console.print(Panel(
            Text(f"{auto_wait} 秒后自动继续...", style=f"{Colors.YELLOW}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        time.sleep(auto_wait)
    else:
        console.print("按 [Enter] 继续...")
        input()


def show_fail_screen(reason="未知错误", logs=None):
    """刷机失败"""
    while True:
        clear_screen()

        console.print(Panel(
            Text(f"{Icons.FAIL} 刷机失败！", style=f"bold {Colors.RED}"),
            border_style=f"{Colors.RED}"
        ))
        console.print()
        console.print(f"失败原因：{reason}", style=f"bold {Colors.RED}")
        console.print()
        console.print("─" * 40)
        console.print()
        console.print("[1] 查看日志")
        console.print("[2] 重试")
        console.print("[3] 返回主菜单")
        console.print()
        choice = input_str("请输入数字 [1-3]：")

        if choice == '1':
            show_logs_screen(logs)
        elif choice == '2':
            return 'retry'
        elif choice == '3':
            return 'back'
        else:
            console.print("无效输入", style=f"{Colors.RED}")


def show_logs_screen(logs=None):
    """显示刷机日志"""
    clear_screen()

    console.print(Panel(
        Text("刷机日志", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()

    if logs:
        for log in logs:
            console.print(f"  {log}", style=f"{Colors.DIM}")
    else:
        console.print("  (无日志)", style=f"{Colors.DIM}")

    console.print()
    console.print(Panel(
        Text("按 [Enter] 返回", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    input()


def record_mac_to_file(mac, model="CR660X"):
    """记录 MAC 地址"""
    global flash_count, recorded_macs

    if mac and mac not in recorded_macs:
        recorded_macs.add(mac)
        flash_count += 1

        # 写入文件
        mac_file = config.inventory.get('mac_file', './mac_list.txt')
        try:
            with open(mac_file, 'a') as f:
                f.write(f"{mac},{model},{time.strftime('%Y-%m-%d %H:%M')}\n")
        except:
            pass

        return True
    return False


def run_cr660x_flow(flow_choice, detected_ip=None):
    """执行 CR660X 刷机流程"""
    global flash_count, flash_logs
    flash_logs = []  # 清空日志

    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")

    if flow_choice == '1':
        # 检查是否检测到 192.168.1.1（第二阶段 IP）
        if detected_ip == '192.168.1.1':
            console.print()
            console.print(Panel(
                Text("⚠️ 检测到路由器处于第二阶段（192.168.1.1）\n请选择 [2] OPENWRT升级自定义固件", style=f"bold {Colors.YELLOW}"),
                border_style=f"{Colors.YELLOW}"
            ))
            console.print()
            input("按 [Enter] 返回...")
            return
        
        # 需要选择运营商
        carrier_choice = show_cr660x_carrier_screen()

        if carrier_choice == 'q' or carrier_choice == 'Q':
            return

        if carrier_choice == '1':
            # 移动/电信 - 需要密码
            password = show_password_input_screen(detected_ip)

            if password == 'q' or password == 'Q':
                return

            flasher = CR660XFlasher(logger=logger)

            # 检测路由器（使用已检测到的 IP，避免二次检测不一致）
            if not flasher.detect_router(detected_ip):
                show_fail_screen("未检测到路由器", flash_logs)
                return

            # Stage 1
            console.print()
            console.print("正在执行第一阶段...", style=f"{Colors.YELLOW}")

            if flasher.stage1_execute(password):
                show_success_screen(
                    step="第一阶段（刷机模式）",
                    next_action="自动进入第二阶段（升级模式）",
                    auto_wait=5
                )

                # Stage 2
                console.print("正在执行第二阶段...", style=f"{Colors.YELLOW}")

                if flasher.stage2_execute():
                    record_mac_to_file(flasher.router_mac, "CR660X")
                    show_success_screen(
                        step="第二阶段（升级模式）",
                        next_action="刷机完成",
                        show_count=True
                    )
                else:
                    show_fail_screen("第二阶段执行失败", flash_logs)
            else:
                show_fail_screen("第一阶段执行失败", flash_logs)

        elif carrier_choice == '2':
            # 联通版本
            flasher = CR660XFlasher(logger=logger)

            # 检测路由器（使用已检测到的 IP，避免二次检测不一致）
            if not flasher.detect_router(detected_ip):
                show_fail_screen("未检测到路由器", flash_logs)
                return

            # Stage 1（联通版）
            console.print()
            console.print("正在执行第一阶段（联通版）...", style=f"{Colors.YELLOW}")

            if flasher.stage1_execute_unicom():
                show_success_screen(
                    step="第一阶段（联通版）",
                    next_action="自动进入第二阶段（升级模式）",
                    auto_wait=5
                )

                # Stage 2
                console.print("正在执行第二阶段...", style=f"{Colors.YELLOW}")

                if flasher.stage2_execute():
                    record_mac_to_file(flasher.router_mac, "CR660X")
                    show_success_screen(
                        step="第二阶段（升级模式）",
                        next_action="刷机完成",
                        show_count=True
                    )
                else:
                    show_fail_screen("第二阶段执行失败", flash_logs)
            else:
                show_fail_screen("第一阶段执行失败（联通版）", flash_logs)

    elif flow_choice == '2':
        # OPENWRT 升级模式
        flasher = CR660XFlasher(logger=logger)

        if flasher.stage2_execute():
            record_mac_to_file(flasher.router_mac, "CR660X")
            show_success_screen(
                step="升级模式",
                next_action="升级完成",
                show_count=True
            )
        else:
            show_fail_screen("升级失败", flash_logs)

    elif flow_choice == '3':
        # UBOOT 上传 Kernel 并升级
        flasher = CR660XFlasher(logger=logger)

        # Stage 3: Uboot HTTP 上传 Kernel
        if flasher.stage3_upload_kernel():
            show_success_screen(
                step="步骤 3 (Uboot→Kernel)",
                next_action="自动进入第二阶段...",
                auto_wait=5
            )

            # Stage 2: 等待 initramfs → 上传最终固件
            console.print("正在执行第二阶段...", style=f"{Colors.YELLOW}")

            if flasher.stage2_execute():
                record_mac_to_file(flasher.router_mac, "CR660X")
                show_success_screen(
                    step="第二阶段（升级模式）",
                    next_action="刷机完成",
                    show_count=True
                )
            else:
                show_fail_screen("第二阶段执行失败", flash_logs)
        else:
            show_fail_screen("Stage 3 执行失败", flash_logs)


def run_jgc_flow(step_choice, online_ip=None):
    """执行 JGC 刷机流程"""
    global flash_count, flash_logs
    flash_logs = []  # 清空日志

    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")

    # 根据检测到的 IP 判断型号
    detect_ips = config.jgc.get('detect_ips', {})
    q10_ip = detect_ips.get('official', '192.168.10.1')
    model = 'Qx' if online_ip != q10_ip else 'Q10'

    if step_choice == '1':
        flasher = JGCFlasher(logger=logger, model=model)

        # Stage 1 — 先自动检测密码，失败则手动输入
        password = flasher.detect_password()
        if not password:
            flash_logs.append("自动获取密码失败，请手动输入")
            password = show_jgc_password_screen(flasher.official_ip)
            if password == 'q' or password == 'Q':
                return

        # 获取认证信息
        stok, sysauth = flasher.get_stok(password)
        if not stok:
            flash_logs.append("认证失败，请检查密码是否正确")
            show_fail_screen("认证失败，请检查密码", flash_logs)
            return

        # 上传固件
        if not flasher.upload_firmware(stok, sysauth):
            show_fail_screen("固件上传失败", flash_logs)
            return

        # 确认升级
        if not flasher.confirm_upgrade(stok, sysauth):
            show_fail_screen("确认升级失败", flash_logs)
            return

        flash_logs.append("确认升级成功，等待路由器重启...")

        # 等待 PDCN 上线
        if not flasher.stage1_wait_pdcn():
            show_fail_screen("等待 PDCN 系统上线超时", flash_logs)
            return

        show_success_screen(
            step="步骤 1/3",
            next_action="即将自动进入步骤 2...",
            auto_wait=5
        )

        # Stage 2
        if flasher.stage2_execute():
            show_success_screen(
                step="步骤 2/3",
                next_action="即将自动进入步骤 3...",
                auto_wait=5
            )

            # Stage 3
            if flasher.stage3_execute():
                record_mac_to_file(flasher.router_mac, "JGC-Q10")
                console.print()
                console.print(Panel(
                    Text(f"{Icons.SUCCESS} 刷机完成!", style=f"bold {Colors.GREEN}"),
                    border_style=f"{Colors.GREEN}"
                ))
                console.print(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}")
                time.sleep(3)
            else:
                show_fail_screen("第三阶段执行失败", flash_logs)
        else:
            show_fail_screen("第二阶段执行失败", flash_logs)

    elif step_choice == '2':
        flasher = JGCFlasher(logger=logger, model=model)

        # Stage 2
        if flasher.stage2_execute():
            show_success_screen(
                step="步骤 2/3",
                next_action="即将自动进入步骤 3...",
                auto_wait=5
            )

            # Stage 3
            if flasher.stage3_execute():
                record_mac_to_file(flasher.router_mac, "JGC-Q10")
                console.print()
                console.print(Panel(
                    Text(f"{Icons.SUCCESS} 刷机完成!", style=f"bold {Colors.GREEN}"),
                    border_style=f"{Colors.GREEN}"
                ))
                console.print(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}")
                time.sleep(3)
            else:
                show_fail_screen("第三阶段执行失败", flash_logs)
        else:
            show_fail_screen("第二阶段执行失败", flash_logs)

    elif step_choice == '3':
        flasher = JGCFlasher(logger=logger, model=model)

        # Stage 3
        if flasher.stage3_execute():
            record_mac_to_file(flasher.router_mac, "JGC-Q10")
            console.print()
            console.print(Panel(
                Text(f"{Icons.SUCCESS} 刷机完成!", style=f"bold {Colors.GREEN}"),
                border_style=f"{Colors.GREEN}"
            ))
            console.print(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}")
            time.sleep(3)
        else:
            show_fail_screen("第三阶段执行失败", flash_logs)

def show_ax3000t_main_screen():
    """AX3000T 主菜单 - 5阶段刷机"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("小米 AX3000T 刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        # 检测在线 IP
        detect_ips = ["192.168.31.1", "192.168.1.1"]
        online_ip = None
        for ip in detect_ips:
            if NetworkTool.ping(ip):
                online_ip = ip
                break

        if online_ip == "192.168.1.1":
            console.print(f"在线路由器：{online_ip} (Uboot/Initramfs)", style=f"bold {Colors.GREEN}")
        elif online_ip:
            console.print(f"在线路由器：{online_ip} (官方系统)", style=f"bold {Colors.GREEN}")
        else:
            console.print("未检测到路由器", style=f"bold {Colors.RED}")
        console.print()

        console.print("请选择刷机流程：", style=f"bold {Colors.WHITE}")
        console.print()
        console.print("[1] Stage 1: 开启SSH", style=f"{Colors.WHITE}")
        console.print("     └─ 检测初始化状态 → 出厂初始化(如需) → 命令注入开SSH", style=f"dim {Colors.DIM}")
        console.print("[2] Stage 2: 刷写Uboot", style=f"{Colors.WHITE}")
        console.print("     └─ SSH上传uboot.fip → mtd write mtd5 → 重启", style=f"dim {Colors.DIM}")
        console.print("[3] Stage 3: TFTP启动Initramfs", style=f"{Colors.WHITE}")
        console.print("     └─ 启动TFTP服务器 → uboot自动获取 → 进入临时系统", style=f"dim {Colors.DIM}")
        console.print("[4] Stage 4: Sysupgrade完整固件", style=f"{Colors.WHITE}")
        console.print("     └─ initramfs中刷入sysupgrade → 持久化到flash", style=f"dim {Colors.DIM}")
        console.print("[5] Stage 5: 刷入自定义Overlay", style=f"{Colors.WHITE}")
        console.print("     └─ 上传overlay包 → 解压到/overlay → 重启生效", style=f"dim {Colors.DIM}")
        console.print("[A] 全自动刷机 (1→2→3→4→5)", style=f"bold {Colors.GREEN}")
        console.print()

        console.print(Panel(
            Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        console.print(Panel(
            Text("按 [r] 重新检测 IP | 按 [q] 返回主菜单", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        choice = input_str("你的选择是：")

        if choice == 'r' or choice == 'R':
            continue
        return choice, online_ip


def show_ax3000t_password_screen(ip="192.168.31.1"):
    """AX3000T 密码输入界面"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("小米 AX3000T 刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
        console.print()
        console.print(Text("💡 管理密码在路由器背面贴纸上", style=f"dim {Colors.YELLOW}"))
        console.print()
        console.print(Panel(
            Text("按 [q] 返回上一步", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        password = input_str("请输入路由器管理密码：")
        if password == 'q' or password == 'Q':
            return password
        if len(password) < 6:
            console.print()
            console.print(Panel(
                Text(f"❌ 密码长度不足 ({len(password)}位)，请重新输入", style=f"bold {Colors.RED}"),
                border_style=f"{Colors.RED}"
            ))
            console.print()
            input("按 [Enter] 继续...")
            continue
        return password


def run_ax3000t_flow(flow_choice, detected_ip=None):
    """执行 AX3000T 刷机流程"""
    global flash_count, flash_logs
    flash_logs = []

    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")

    flasher = AX3000TFlasher(logger=logger)

    def wait_reboot_step(prompt, target_ip="192.168.1.1"):
        """等待用户操作硬件并确认"""
        console.print()
        console.print(Panel(
            Text(f"⚠️  {prompt}", style=f"bold {Colors.YELLOW}"),
            border_style=f"{Colors.YELLOW}"
        ))
        console.print()
        console.print(Text("准备好后按 Enter 继续等待...", style=f"dim {Colors.YELLOW}"))
        input()
        console.print(f"等待 {target_ip} 上线...", style=f"{Colors.YELLOW}")
        for i in range(60, 0, -1):
            if NetworkTool.ping(target_ip):
                console.print(f"\n{target_ip} 已上线!", style=f"bold {Colors.GREEN}")
                return True
            if i % 20 == 0:
                console.print(f"  剩余 {i} 秒...", style=f"{Colors.DIM}")
            time.sleep(1)
        console.print(f"\n{target_ip} 未上线", style=f"{Colors.RED}")
        return False

    # ============================================================
    # Stage 1: 开启 SSH
    # ============================================================
    if flow_choice == '1':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        # 先检测初始化状态
        init_state = flasher.check_init()
        init_code = init_state.get("init", -1)

        if init_code == -1:
            show_fail_screen("路由器不可达", flash_logs)
            return

        if init_code == 0:
            # init=0: 已被初始化过，需要工人恢复出厂
            show_fail_screen(
                "⚠️  路由器已被初始化过\n\n"
                "请工人按住路由器背面 Reset 孔 5-10 秒\n"
                "恢复出厂设置后再重试 Stage 1",
                flash_logs
            )
            return

        # init=1: 出厂状态，直接初始化
        console.print("\n路由器为出厂状态，自动初始化中...", style=f"{Colors.YELLOW}")
        console.print("  (SSID: Xiaomi_AX3000T, 密码: 12345678)", style=f"dim {Colors.DIM}")

        result = flasher.stage1_enable_ssh("12345678", "Xiaomi_AX3000T", "12345678")
        if result == 'ok':
            record_mac_to_file(flasher.router_mac, "AX3000T")
            show_success_screen("Stage 1 (开启SSH)", "SSH已就绪 (root/root)", show_count=True)
        else:
            show_fail_screen("开启SSH失败", flash_logs)

    # ============================================================
    # Stage 2: 刷 Uboot
    # ============================================================
    elif flow_choice == '1.5':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        if persist["stok"]:
            flasher.stok = persist["stok"]
        else:
            console.print("重新登录...", style=f"{Colors.YELLOW}")
            r = subprocess.run([sys.executable, str(flasher.SCRIPTS_DIR / "login_get_stok.py"),
                "--ip", flasher.router_ip, "--pwd", "12345678"],
                capture_output=True, text=True, timeout=30)
            try:
                flasher.stok = json.loads(r.stdout).get("stok")
            except: pass
            if not flasher.stok:
                show_fail_screen("登录失败", flash_logs); return
        console.print("\n正在执行 Stage 1.5: WiFi注入开SSH...", style=f"{Colors.YELLOW}")
        if not flasher._run("enable_ssh.py", "--ip", flasher.router_ip, "--stok", flasher.stok, timeout=180).get("error"):
            flasher._wait_ssh()
            r = flasher._run("get_wifi_password.py", "--ip", flasher.router_ip, "--stok", flasher.stok)
            if "error" not in r:
                persist["ssh_password"] = r.get("password")
                show_success_screen("Stage 1.5 (开SSH)", f"SSH已就绪 (root/{r.get('password')})", show_count=True)
            else:
                show_fail_screen("获取密码失败", flash_logs)
        else:
            show_fail_screen("SSH注入失败，请检查辅助WiFi是否在线", flash_logs)

    elif flow_choice == '2':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        console.print("\n正在执行 Stage 2: 刷写Uboot...", style=f"{Colors.YELLOW}")
        if flasher.stage2_flash_uboot():
            show_success_screen(
                "Stage 2 (刷写Uboot)",
                "刷写完成，路由器自动重启\n"
                "重启后 uboot 会尝试启动，失败则回退 TFTP",
                auto_wait=3,
            )
        else:
            show_fail_screen("刷写Uboot失败", flash_logs)

    # ============================================================
    # Stage 3: TFTP 启动 initramfs
    # ============================================================
    elif flow_choice == '3':
        # 检测 192.168.1.1:22 是否开放来判断是否已在 initramfs 中
        import socket
        in_initramfs = False
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        if s.connect_ex(('192.168.1.1', 22)) == 0:
            in_initramfs = True
        s.close()

        if in_initramfs:
            flasher.router_ip = "192.168.1.1"
            console.print(Panel(
                Text("检测到 192.168.1.1 在线，路由器已在 initramfs 中",
                     style=f"bold {Colors.GREEN}"),
                border_style=f"{Colors.GREEN}"
            ))
            console.print()
            console.print("如需重新 TFTP 请先断开路由器电源再重试", style=f"dim {Colors.YELLOW}")
            console.print()
            input("按 [Enter] 返回菜单...")
            return
        else:
            itb = list(flasher.FIRMWARE_DIR.glob("*initramfs-recovery*"))
            if not itb:
                show_fail_screen("未找到 initramfs-recovery.itb", flash_logs)
                return

            console.print(f"TFTP 服务器启动，等待 uboot 连接...", style=f"{Colors.YELLOW}")
            console.print(Text("按 q 取消等待", style=f"dim {Colors.YELLOW}"))

            proc = subprocess.Popen(
                [sys.executable, str(flasher.SCRIPTS_DIR / "tftpd.py"),
                 str(flasher.FIRMWARE_DIR)],
                stdout=subprocess.DEVNULL,
                cwd=str(flasher.FIRMWARE_DIR),
            )

            import tty, termios, select, os
            fd = sys.stdin.fileno()
            deadline = time.time() + 300
            if os.isatty(fd):
                old = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while True:
                        if proc.poll() is not None:
                            break
                        if time.time() > deadline:
                            proc.kill()
                            proc.wait()
                            console.print("\nTFTP 超时(5分钟)，未收到连接", style=f"{Colors.YELLOW}")
                            return
                        if select.select([sys.stdin], [], [], 0.5)[0]:
                            if sys.stdin.read(1).lower() == 'q':
                                raise KeyboardInterrupt
                except (KeyboardInterrupt, EOFError):
                    proc.kill()
                    proc.wait()
                    console.print("\n已取消", style=f"{Colors.YELLOW}")
                    return
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            else:
                try:
                    proc.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    console.print("\nTFTP 超时(5分钟)，未收到连接", style=f"{Colors.YELLOW}")
                    return

            if proc.returncode != 0:
                console.print(f"\nTFTP 异常退出 (exit={proc.returncode})", style=f"{Colors.RED}")
                return

            console.print("TFTP 传输完成", style=f"{Colors.GREEN}")
            show_success_screen("Stage 3 (TFTP启动)", "initramfs 已就绪 (192.168.1.1)")

    # ============================================================
    # Stage 4: sysupgrade 完整固件
    # ============================================================
    elif flow_choice == '4':
        flasher.router_ip = detected_ip or "192.168.1.1"

        console.print("\n正在执行 Stage 4: Sysupgrade完整固件...", style=f"{Colors.YELLOW}")
        if flasher.stage4_sysupgrade():
            show_success_screen(
                "Stage 4 (Sysupgrade)",
                "系统正在重启并刷入完整固件\n"
                "完成后执行 Stage 5: 刷入自定义Overlay",
                auto_wait=5,
            )
        else:
            show_fail_screen("Sysupgrade 失败", flash_logs)

    # ============================================================
    # Stage 5: 刷入自定义 overlay
    # ============================================================
    elif flow_choice == '5':
        flasher.router_ip = detected_ip or "192.168.1.1"

        if not NetworkTool.ping(flasher.router_ip):
            if not wait_reboot_step("请确保路由器已启动到完整系统 (192.168.1.1)"):
                show_fail_screen("路由器未上线", flash_logs)
                return

        console.print("\n正在执行 Stage 5: 刷入自定义Overlay...", style=f"{Colors.YELLOW}")
        if flasher.stage5_apply_overlay():
            show_success_screen(
                "Stage 5 (Overlay)",
                "刷入完成，路由器自动重启中",
            )
        else:
            show_fail_screen("刷入Overlay失败", flash_logs)

    # ============================================================
    # 全自动
    # ============================================================
    elif flow_choice == 'a' or flow_choice == 'A':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        # 检测初始化状态
        init_state = flasher.check_init()
        init_code = init_state.get("init", -1)

        if init_code == -1:
            show_fail_screen("路由器不可达", flash_logs)
            return

        if init_code == 0:
            show_fail_screen(
                "⚠️  路由器已被初始化过\n\n"
                "请工人按住路由器背面 Reset 孔 5-10 秒\n"
                "恢复出厂设置后再重试全自动刷机",
                flash_logs
            )
            return

        console.print("\n全自动刷机启动!", style=f"bold {Colors.GREEN}")
        console.print("  (SSID: Xiaomi_AX3000T, 密码: 12345678)", style=f"dim {Colors.DIM}")

        if flasher.auto_flash("12345678", "Xiaomi_AX3000T", "12345678"):
            show_success_screen("全自动刷机完成", "路由器已刷好并配置完毕")
        else:
            show_fail_screen("全自动刷机失败", flash_logs)


# ============================================================
# AX3600 菜单 + 流程
# ============================================================

def show_ax3600_main_screen():
    """AX3600 主菜单"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("小米 AX3600 刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        detect_ips = ["192.168.31.1", "192.168.1.1"]
        online_ip = None
        for ip in detect_ips:
            if NetworkTool.ping(ip):
                online_ip = ip
                break

        if online_ip:
            console.print(f"在线路由器：{online_ip}", style=f"bold {Colors.GREEN}")
        else:
            console.print("未检测到路由器", style=f"bold {Colors.RED}")
        console.print()

        console.print("请选择刷机流程：", style=f"bold {Colors.WHITE}")
        console.print()
        console.print("[1] Stage 1: 开启SSH", style=f"{Colors.WHITE}")
        console.print("     └─ 检测 → 初始化(如需) → 降级(如需) → 注入开SSH", style=f"dim {Colors.DIM}")
        console.print("[2] Stage 2: 刷过渡固件到备胎分区", style=f"{Colors.WHITE}")
        console.print("     └─ 上传R3600_mtd12.bin → 写入备胎 → 切启动标志 → 重启", style=f"dim {Colors.DIM}")
        console.print("[3] Stage 3: 刷MIBIB+Uboot", style=f"{Colors.WHITE}")
        console.print("     └─ 过渡OpenWRT中 → fw_setenv → mtd write mtd1+mtd7", style=f"dim {Colors.DIM}")
        console.print("[4] Stage 4: Uboot上传最终固件", style=f"{Colors.WHITE}")
        console.print("     └─ curl上传factory.ubi → uboot自动刷写+重启", style=f"dim {Colors.DIM}")
        console.print("[A] 全自动刷机 (1→2→3→4)", style=f"bold {Colors.GREEN}")
        console.print()

        console.print(Panel(
            Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        console.print(Panel(
            Text("按 [r] 重新检测 IP | 按 [q] 返回主菜单", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()
        choice = input_str("你的选择是：")
        if choice == 'r' or choice == 'R':
            continue
        return choice, online_ip


def run_ax3600_flow(flow_choice, detected_ip=None):
    """执行 AX3600 刷机流程"""
    global flash_count, flash_logs
    flash_logs = []

    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")

    flasher = AX3600Flasher(logger=logger)

    if flow_choice == '1':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        init = flasher.check_init()
        if init.get("init") == -1:
            show_fail_screen("路由器不可达", flash_logs)
            return

        if init.get("init") == 0:
            show_fail_screen(
                "⚠️  路由器已被初始化过\n请工人按住 Reset 孔 5-10 秒恢复出厂设置后再重试",
                flash_logs
            )
            return

        console.print("\n路由器为出厂状态，自动初始化中...", style=f"{Colors.YELLOW}")
        console.print("  (SSID: Xiaomi_AX3600, 密码: 12345678)", style=f"dim {Colors.DIM}")

        result = flasher.stage1_enable_ssh("12345678", "Xiaomi_AX3600", "12345678")
        if result == 'ok':
            record_mac_to_file(flasher.router_mac, "AX3600")
            show_success_screen("Stage 1 (开启SSH)", "SSH已就绪 (root/root)", show_count=True)
        else:
            show_fail_screen("开启SSH失败", flash_logs)

    elif flow_choice == '1.5':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        if persist["stok"]:
            flasher.stok = persist["stok"]
        else:
            console.print("重新登录...", style=f"{Colors.YELLOW}")
            r = subprocess.run([sys.executable, str(flasher.SCRIPTS_DIR / "login_get_stok.py"),
                "--ip", flasher.router_ip, "--pwd", "12345678"],
                capture_output=True, text=True, timeout=30)
            try:
                flasher.stok = json.loads(r.stdout).get("stok")
            except: pass
            if not flasher.stok:
                show_fail_screen("登录失败", flash_logs); return
        console.print("\n正在执行 Stage 1.5: WiFi注入开SSH...", style=f"{Colors.YELLOW}")
        if not flasher._run("enable_ssh.py", "--ip", flasher.router_ip, "--stok", flasher.stok, timeout=180).get("error"):
            flasher._wait_ssh()
            r = flasher._run("get_wifi_password.py", "--ip", flasher.router_ip, "--stok", flasher.stok)
            if "error" not in r:
                persist["ssh_password"] = r.get("password")
                show_success_screen("Stage 1.5 (开SSH)", f"SSH已就绪 (root/{r.get('password')})", show_count=True)
            else:
                show_fail_screen("获取密码失败", flash_logs)
        else:
            show_fail_screen("SSH注入失败，请检查辅助WiFi是否在线", flash_logs)

    elif flow_choice == '2':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        console.print("\n正在执行 Stage 2: 刷过渡固件...", style=f"{Colors.YELLOW}")
        if flasher.stage2_flash_transition():
            show_success_screen(
                "Stage 2 (刷过渡固件)",
                "路由器重启中，等待过渡 OpenWRT 就绪后执行 Stage 3",
                auto_wait=3,
            )
        else:
            show_fail_screen("刷过渡固件失败", flash_logs)

    elif flow_choice == '3':
        if not NetworkTool.ping("192.168.1.1"):
            show_fail_screen("过渡 OpenWRT 不在线 (192.168.1.1)", flash_logs)
            return

        flasher.router_ip = "192.168.1.1"
        console.print("\n正在执行 Stage 3: 刷MIBIB+Uboot...", style=f"{Colors.YELLOW}")
        if flasher.stage3_flash_uboot():
            show_success_screen(
                "Stage 3 (刷MIBIB+Uboot)",
                "刷写完成，路由器自动重启中\n"
                "按住 Reset 上电进入 uboot 模式 (蓝灯)，然后执行 Stage 4",
                auto_wait=3,
            )
        else:
            show_fail_screen("刷MIBIB+Uboot失败", flash_logs)

    elif flow_choice == '4':
        console.print("\n请确认路由器是否已进入 Uboot 模式", style=f"{Colors.YELLOW}")
        console.print("  (断电 → 按住 Reset → 上电 → 蓝灯亮起)", style=f"{Colors.DIM}")
        console.print("  192.168.1.1 应可 ping 通", style=f"{Colors.DIM}")
        console.print()
        input("确认后按 Enter 开始等待 Uboot 上线...")

        console.print("等待 192.168.1.1 (Uboot) 上线...", style=f"{Colors.YELLOW}")
        for i in range(120, 0, -1):
            if NetworkTool.ping("192.168.1.1"):
                console.print("Uboot 已就绪!", style=f"{Colors.GREEN}")
                break
            if i % 20 == 0:
                console.print(f"  剩余 {i} 秒...", style=f"{Colors.DIM}")
            time.sleep(1)
        else:
            show_fail_screen("Uboot 未上线，请检查路由器是否已进入 Uboot 模式", flash_logs)
            return

        console.print("正在执行 Stage 4: Uboot上传固件...", style=f"{Colors.YELLOW}")
        if flasher.stage4_uboot_upload():
            show_success_screen(
                "Stage 4 (Uboot上传)",
                "上传完成，uboot 正在刷写\n"
                "等待路由器自动重启进入 OpenWRT",
                auto_wait=3,
            )
        else:
            show_fail_screen("Uboot上传失败", flash_logs)

    elif flow_choice in ('a', 'A'):
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs)
            return

        init = flasher.check_init()
        if init.get("init") == 0:
            show_fail_screen("路由器已被初始化，请恢复出厂设置", flash_logs)
            return

        console.print("\n全自动刷机启动!", style=f"bold {Colors.GREEN}")
        console.print("  (密码: 12345678)", style=f"dim {Colors.DIM}")

        if flasher.auto_flash("12345678"):
            show_success_screen("全自动刷机完成", "路由器已刷好 OpenWRT")
        else:
            show_fail_screen("全自动刷机失败", flash_logs)



# ============================================================
# AX6 菜单 + 流程
# ============================================================

def show_ax6_main_screen():
    """AX6 主菜单"""
    while True:
        clear_screen()
        console.print(Panel(Text("红米 AX6 刷机模式", style=f"bold {Colors.CYAN}"), border_style=f"{Colors.BLUE}"))
        console.print()
        detect_ips = ["192.168.31.1", "192.168.1.1"]
        online_ip = None
        for ip in detect_ips:
            if NetworkTool.ping(ip):
                online_ip = ip
                break
        if online_ip:
            console.print(f"在线路由器：{online_ip}", style=f"bold {Colors.GREEN}")
        else:
            console.print("未检测到路由器", style=f"bold {Colors.RED}")
        console.print()
        console.print("请选择刷机流程：", style=f"bold {Colors.WHITE}")
        console.print()
        console.print("[1] Stage 1: 开SSH", style=f"{Colors.WHITE}")
        console.print("     └─ 检测 → 初始化 → 降级 → WiFi注入 → 获取密码", style=f"dim {Colors.DIM}")

        console.print("[2] Stage 2: 刷过渡固件到备胎", style=f"{Colors.WHITE}")
        console.print("     └─ mtd write xiaomimtd12.bin → nvram设置 → reboot", style=f"dim {Colors.DIM}")
        console.print("[3] Stage 3: 刷MIBIB+Uboot", style=f"{Colors.WHITE}")
        console.print("     └─ 过渡OpenWRT → mtd write mtd1+mtd7 → reboot→uboot", style=f"dim {Colors.DIM}")
        console.print("[4] Stage 4: Uboot上传最终固件", style=f"{Colors.WHITE}")
        console.print("     └─ curl上传factory.ubi → uboot自动刷写+重启", style=f"dim {Colors.DIM}")
        console.print("[5] Stage 5: 刷入自定义Overlay", style=f"{Colors.WHITE}")
        console.print("     └─ 上传overlay → tar -xzf /overlay → reboot", style=f"dim {Colors.DIM}")
        console.print("[A] 全自动刷机 (1→2→3→4→5)", style=f"bold {Colors.GREEN}")
        console.print()
        console.print(Panel(Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"), border_style=f"{Colors.BLUE}"))
        console.print()
        console.print(Panel(Text("按 [r] 重新检测 | 按 [q] 返回主菜单", style=f"{Colors.WHITE}"), border_style=f"{Colors.BLUE}"))
        console.print()
        choice = input_str("你的选择是：")
        if choice == 'r' or choice == 'R':
            continue
        return choice, online_ip


def run_ax6_flow(flow_choice, detected_ip=None):
    global flash_count, flash_logs
    flash_logs = []
    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")
    flasher = AX6Flasher(logger=logger)

    # 通用：等待 uboot 上线（IPQ807x uboot ARP 有 bug，需静态 ARP）
    def wait_uboot():
        console.print("等待 192.168.1.1 (Uboot) 上线...", style=f"{Colors.YELLOW}")
        # 从过渡 OpenWRT 拿到的 MAC，写死 ARP 绕过 uboot 的 ARP 协议 bug
        if flasher.router_mac:
            subprocess.run(["arp", "-s", "192.168.1.1", flasher.router_mac],
                           capture_output=True, timeout=5)
        # arping 双向建 ARP 表
        subprocess.run(["arping", "-c", "3", "-w", "5", "192.168.1.1"],
                       capture_output=True, timeout=10)
        for i in range(30, 0, -1):
            if NetworkTool.ping("192.168.1.1"):
                console.print("Uboot 已就绪!", style=f"{Colors.GREEN}")
                return True
            if i % 10 == 0:
                console.print(f"  剩余 {i} 秒...", style=f"{Colors.DIM}")
            time.sleep(1)
        return False

    if flow_choice == '1':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        console.print("\n正在执行 Stage 1: 开SSH...", style=f"{Colors.YELLOW}")
        console.print("  (密码: 12345678, WiFi: AX6-EXPLOIT)", style=f"dim {Colors.DIM}")
        result = flasher.stage1_enable_ssh("12345678", "Xiaomi_AX6", "12345678")
        if result == 'ok':
            persist["ssh_password"] = flasher.ssh_password
            persist["stok"] = flasher.stok
            show_success_screen("Stage 1 (开SSH)", f"SSH已就绪 (root/{flasher.ssh_password})",
                               show_count=True)
        else:
            show_fail_screen("开SSH失败", flash_logs)

    elif flow_choice == '2':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        if persist["ssh_password"]:
            flasher.ssh_password = persist["ssh_password"]
        else:
            console.print("获取 5G WiFi 密码...", style=f"{Colors.YELLOW}")
            flasher.router_ip = detected_ip or "192.168.31.1"
            # 登录 + 取密码一条龙
            p = subprocess.run(
                f"cd {flasher.SCRIPTS_DIR} && "
                f"stok=$(python3 login_get_stok.py --ip {flasher.router_ip} --pwd 12345678 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"stok\"])') && "
                f"python3 get_wifi_password.py --ip {flasher.router_ip} --stok $stok 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"password\"])'",
                capture_output=True, text=True, timeout=30, shell=True,
            )
            pw = p.stdout.strip()
            if pw:
                flasher.ssh_password = pw
                console.print(f"密码: {pw}", style=f"{Colors.DIM}")
        console.print("\n正在执行 Stage 2: 刷过渡固件...", style=f"{Colors.YELLOW}")
        if flasher.stage2_flash_transition():
            show_success_screen("Stage 2 (刷过渡固件)", "路由器重启中，随后执行 Stage 3", auto_wait=3)
        else:
            show_fail_screen("刷过渡固件失败", flash_logs)

    elif flow_choice == '3':
        if not NetworkTool.ping("192.168.1.1"):
            show_fail_screen("过渡 OpenWRT 不在线", flash_logs); return
        # 从过渡 OpenWRT 拿真实 MAC 地址，给 Stage 4 静态 ARP 用
        ok, out = ShellTool.ssh_cmd("192.168.1.1", "root", "",
                                     "cat /sys/class/net/eth0/address", timeout=5)
        if ok:
            flasher.router_mac = out.strip()
            console.print(f"   MAC: {flasher.router_mac}", style=f"{Colors.DIM}")
        console.print("\n正在执行 Stage 3: 刷MIBIB+Uboot...", style=f"{Colors.YELLOW}")
        flasher.router_ip = "192.168.1.1"
        if flasher.stage3_flash_uboot():
            show_success_screen("Stage 3 (刷MIBIB+Uboot)",
                "重启中，按住 Reset 蓝灯亮松手后执行 Stage 4", auto_wait=3)
        else:
            show_fail_screen("刷MIBIB+Uboot失败", flash_logs)

    elif flow_choice == '4':
        console.print("\n确认 uboot 已就绪", style=f"{Colors.YELLOW}")
        console.print("  Stage 3 重启后按住 Reset，蓝灯亮松手", style=f"{Colors.DIM}")
        input("\n确认后按 Enter 开始等待 uboot 上线...")
        if not wait_uboot():
            show_fail_screen("Uboot 未上线", flash_logs); return
        console.print("正在执行 Stage 4: Uboot上传固件...", style=f"{Colors.YELLOW}")
        if flasher.stage4_uboot_upload():
            show_success_screen("Stage 4 (Uboot上传)", "上传完成，正在刷写，等待重启后执行 Stage 5", auto_wait=3)
        else:
            show_fail_screen("Uboot上传失败", flash_logs)

    elif flow_choice == '5':
        if not NetworkTool.ping("192.168.1.1"):
            show_fail_screen("路由器不在线 (192.168.1.1)", flash_logs); return
        flasher.router_ip = "192.168.1.1"
        console.print("\n正在执行 Stage 5: 刷入Overlay...", style=f"{Colors.YELLOW}")
        if flasher.stage5_apply_overlay():
            show_success_screen("Stage 5 (Overlay)", "刷入完成，路由器自动重启中")
        else:
            show_fail_screen("刷入Overlay失败", flash_logs)

    elif flow_choice in ('a', 'A'):
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        init = flasher.check_init()
        if init.get("init") == 0:
            show_fail_screen("路由器已被初始化，请恢复出厂设置", flash_logs); return
        console.print("\n全自动刷机启动!", style=f"bold {Colors.GREEN}")
        if flasher.auto_flash("12345678"):
            show_success_screen("全自动刷机完成", "AX6 已完成全部刷机")
        else:
            show_fail_screen("全自动刷机失败", flash_logs)


def _jgc_kill_chfs():
    """清理所有 chfs 进程，防止进程堆积"""
    try:
        # 查找并 kill 所有 chfs 进程
        subprocess.run(
            "pkill -f 'chfs' 2>/dev/null || true",
            shell=True, timeout=5
        )
        time.sleep(0.5)  # 等待进程完全退出
    except:
        pass


def _jgc_ensure_chfs():
    """JGC 页面进入时自动拉起 chfs 文件服务器"""
    chfs_cfg = config.jgc.get('chfs', {})
    chfs_ip = chfs_cfg.get('ip', '192.168.123.5')
    chfs_port = chfs_cfg.get('port', 8080)

    # 检查是否已运行
    try:
        r = requests.get(f"http://{chfs_ip}:{chfs_port}", timeout=1)
        return  # 已在运行
    except:
        pass

    # 先清理可能残留的旧 chfs 进程
    _jgc_kill_chfs()

    # 解析 chfs 二进制路径和共享目录（相对于 src/ 目录）
    src_dir = Path(__file__).parent
    chfs_path = src_dir / chfs_cfg.get('binary', '../JGC-Q10/chfs-linux-amd64-3.1')
    share_path = src_dir / chfs_cfg.get('share_path', './firmware/jgc')

    chfs_path = chfs_path.resolve()
    share_path = share_path.resolve()

    if not chfs_path.exists():
        flash_logs.append(f"chfs 二进制文件不存在: {chfs_path}")
        return

    if not share_path.exists():
        flash_logs.append(f"chfs 共享目录不存在: {share_path}")
        return

    try:
        cmd = f'nohup "{chfs_path}" -port {chfs_port} -path "{share_path}" > /dev/null 2>&1 &'
        subprocess.run(cmd, shell=True, timeout=5)
        time.sleep(1)
        flash_logs.append(f"chfs 服务已启动 ({chfs_ip}:{chfs_port})")
    except Exception as e:
        flash_logs.append(f"chfs 启动失败: {e}")


# =============================================
# AX5 菜单 + 流程
# =============================================

def show_ax5_main_screen():
    """AX5 主菜单（仅 Stage 1: 开SSH）"""
    while True:
        clear_screen()

        console.print(Panel(
            Text("红米 AX5 刷机模式", style=f"bold {Colors.CYAN}"),
            border_style=f"{Colors.BLUE}"
        ))
        console.print()

        detected_ip = None
        for ip in ["192.168.31.1", "192.168.1.1"]:
            if NetworkTool.ping(ip):
                detected_ip = ip
                break

        if detected_ip:
            console.print(f"在线路由器：{detected_ip}", style=f"bold {Colors.GREEN}")
        else:
            console.print("未检测到路由器", style=f"bold {Colors.RED}")
        console.print()

        console.print("请选择刷机流程：", style=f"bold {Colors.WHITE}")
        console.print()
        console.print("[1] Stage 1: 开SSH", style=f"{Colors.WHITE}")
        console.print("     └─ 检测 → 初始化 → 降级 → 注入 → 获取SSH", style=f"dim {Colors.DIM}")
        console.print("[2] Stage 2: 刷过渡 OpenWRT", style=f"{Colors.WHITE}")
        console.print("     └─ SCP上传 → ubiformat备胎 → nvram → reboot", style=f"dim {Colors.DIM}")
        console.print()
        console.print(Panel(Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"), border_style=f"{Colors.BLUE}"))
        console.print()
        console.print(Panel(Text("按 [r] 重新检测 | 按 [q] 返回主菜单", style=f"{Colors.WHITE}"), border_style=f"{Colors.BLUE}"))
        console.print()
        choice = input_str("你的选择是：")
        if choice == 'r' or choice == 'R':
            continue
        return choice, detected_ip


def run_ax5_flow(flow_choice, detected_ip=None):
    global flash_count, flash_logs
    flash_logs = []
    def logger(msg):
        flash_logs.append(msg)
        console.print(f"  {msg}", style=f"{Colors.DIM}")
    flasher = AX5Flasher(logger=logger)

    if flow_choice == '1':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        # 自动获取本机 IP（用于 chfs 提供 unlock_ssh.sh）
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((flasher.router_ip, 80))
            flasher.local_ip = s.getsockname()[0]
            s.close()
        except:
            flasher.local_ip = "192.168.31.254"
        console.print(f"  本机 IP: {flasher.local_ip}", style=f"{Colors.DIM}")
        console.print("\n正在执行 Stage 1: 开SSH...", style=f"{Colors.YELLOW}")
        console.print("  (密码: 12345678)", style=f"dim {Colors.DIM}")
        result = flasher.stage1_enable_ssh("12345678")
        if result == 'ok':
            flash_count += 1
            record_mac_to_file(flasher.router_mac, "AX5")
            persist["ssh_password"] = flasher.ssh_password
            persist["stok"] = flasher.stok
            show_success_screen("Stage 1 (开SSH)", f"SSH已就绪 (root/password)", show_count=True)
        else:
            show_fail_screen("开SSH失败", flash_logs)

    elif flow_choice == '2':
        if not flasher.detect_router(detected_ip):
            show_fail_screen("未检测到路由器", flash_logs); return
        flasher.ssh_password = persist.get("ssh_password", "password")
        console.print("\n正在执行 Stage 2: 刷过渡 OpenWRT...", style=f"{Colors.YELLOW}")
        if flasher.stage2_flash_transition():
            show_success_screen("Stage 2 (刷过渡固件)", "路由器重启中，IP 将变为 192.168.1.1", auto_wait=3)
        else:
            show_fail_screen("刷过渡固件失败", flash_logs)


def main():
    """主函数"""
    console.print()
    console.print("=" * 50, style=f"bold {Colors.CYAN}")
    console.print("路由器刷机工具 v2.0", style=f"bold {Colors.CYAN}")
    console.print("=" * 50)
    console.print()

    input("按 [Enter] 开始...")

    while True:
        choice = show_start_screen()

        if choice == 'q' or choice == 'Q':
            console.print("\n退出程序", style=f"{Colors.YELLOW}")
            break

        if choice == '1':
            # CR660X
            while True:
                flow_choice, detected_ip = show_cr660x_main_screen()

                if flow_choice == 'q' or flow_choice == 'Q':
                    break

                run_cr660x_flow(flow_choice, detected_ip)

        elif choice == '2':
            # JGC — 进入 JGC 页面时自动拉起 chfs
            _jgc_ensure_chfs()

            while True:
                step_choice, online_ip = show_jgc_menu_screen()

                if step_choice == 'q' or step_choice == 'Q':
                    break

                run_jgc_flow(step_choice, online_ip)

        elif choice == '3':
            # AX3000T
            while True:
                flow_choice, detected_ip = show_ax3000t_main_screen()

                if flow_choice == 'q' or flow_choice == 'Q':
                    break

                run_ax3000t_flow(flow_choice, detected_ip)

        elif choice == '4':
            # AX3600
            while True:
                flow_choice, detected_ip = show_ax3600_main_screen()

                if flow_choice == 'q' or flow_choice == 'Q':
                    break

                run_ax3600_flow(flow_choice, detected_ip)

        elif choice == '5':
            # AX6
            while True:
                flow_choice, detected_ip = show_ax6_main_screen()
                if flow_choice == 'q' or flow_choice == 'Q':
                    break
                run_ax6_flow(flow_choice, detected_ip)

        elif choice == '6':
            # AX5
            while True:
                flow_choice, detected_ip = show_ax5_main_screen()
                if flow_choice == 'q' or flow_choice == 'Q':
                    break
                run_ax5_flow(flow_choice, detected_ip)

        else:
            console.print("\n无效输入，请重新选择", style=f"{Colors.RED}")
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n程序已退出", style=f"{Colors.YELLOW}")
        # 清理 chfs 进程
        _jgc_kill_chfs()
        sys.exit(0)
    finally:
        # 确保程序退出时清理 chfs 进程
        _jgc_kill_chfs()
