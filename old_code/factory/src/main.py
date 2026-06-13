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
from utils import NetworkTool

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
    console.print()
    console.print(Panel(
        Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    return input_str("请输入数字 [1-2]：")


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
