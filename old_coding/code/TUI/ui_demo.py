#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由器刷机工具 TUI Demo
仅展示界面跳转逻辑，不执行真实刷机
支持真实交互输入
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import sys
import os

console = Console()

# 全局计数器
flash_count = 0
recorded_macs = set()  # 已记录的MAC地址

# 颜色配置
class Colors:
    GREEN = "green"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    WHITE = "white"
    CYAN = "cyan"
    DIM = "dim"

# 状态图标
class Icons:
    SUCCESS = "✅"
    FAIL = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    LOADING = "⏳"
    ONLINE = "●"
    OFFLINE = "○"

def clear_screen():
    """清屏"""
    os.system('clear')

def get_hostname():
    """获取主机名"""
    return os.getenv('HOSTNAME', 'router-flash-01')

def input_str(prompt=""):
    """输入字符串"""
    return input(prompt).strip()

def show_start_screen():
    """开始界面 - 机型选择"""
    clear_screen()
    
    title = Text("路由器刷机工具 v1.0", style=f"bold {Colors.CYAN}")
    node = Text(f"工作节点：{get_hostname()}", style=f"{Colors.WHITE}")
    
    title_panel = Panel(
        f"{title}\n{node}",
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    )
    
    console.print(title_panel)
    console.print()
    
    content = Text()
    content.append("请选择要刷机的路由器型号：\n\n", style=f"bold {Colors.WHITE}")
    content.append("[1] CR660X 小米/联通路由器", style=f"{Colors.WHITE}")
    content.append("\n[2] JGC Q10/Q20 路由器", style=f"{Colors.WHITE}")
    
    console.print(content)
    
    status = Text(f"已完成: 0 台", style=f"{Colors.WHITE}")
    console.print()
    console.print(Panel(
        status,
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    console.print()
    
    return input_str("请输入数字 [1-2]：")

def show_cr660x_main_screen():
    """CR660X 主菜单 - 选择刷机流程"""
    global flash_count
    
    clear_screen()
    
    title = "CR660X/TR660X 批量刷机模式"
    
    console.print(Panel(
        Text(title, style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    
    # 显示在线IP
    console.print(f"在线路由器：192.168.10.1", style=f"{Colors.GREEN}")
    console.print()
    
    content = Text()
    content.append("请选择刷机流程：\n\n", style=f"bold {Colors.WHITE}")
    
    content.append("[1] 官方系统破解刷入BOOTLOADER和KERNEL", style=f"{Colors.WHITE}")
    content.append("       └─ 刷入后自动进入第二阶段\n", style=f"dim {Colors.DIM}")
    content.append("[2] OPENWRT升级自定义固件", style=f"{Colors.WHITE}")
    content.append("       └─ 升级已有openwrt系统\n", style=f"dim {Colors.DIM}")
    
    console.print(content)
    console.print()
    
    # 显示计数器
    console.print(Panel(
        Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    console.print()
    console.print(Panel(
        Text("按 [q] 返回主菜单", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    console.print()
    
    return input_str("你的选择是：")

def record_mac_to_file(mac, model="CR660X"):
    """记录MAC地址到本地存货表"""
    global flash_count
    
    # 模拟写入本地文件
    # 实际实现时会检查本地mac_list.txt或类似文件
    if mac not in recorded_macs:
        recorded_macs.add(mac)
        flash_count += 1
        # 这里应该写入文件，demo只打印日志
        console.print(f"\n[记录MAC] {mac} 已写入存货表 ({model})", style=f"dim {Colors.DIM}")
        return True
    return False

def show_cr660x_carrier_screen():
    """CR660X 选择运营商（仅第一步需要）"""
    clear_screen()
    
    title = "CR660X/TR660X 批量刷机模式"
    
    console.print(Panel(
        Text(title, style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    
    console.print("所处模式：1 - 刷机模式", style=f"{Colors.WHITE}")
    console.print()
    
    content = Text()
    content.append("请选择运营商：\n\n", style=f"bold {Colors.WHITE}")
    
    content.append("[1] 中国移动 / 中国电信", style=f"{Colors.WHITE}")
    content.append("       └─ 需要输入路由器密码\n", style=f"dim {Colors.DIM}")
    content.append("[2] 中国联通", style=f"{Colors.WHITE}")
    content.append("       └─ 恢复出厂设置，自动刷机\n", style=f"dim {Colors.DIM}")
    
    console.print(content)
    console.print()
    console.print(Panel(
        Text("提示：联通版本会恢复出厂设置，不需要密码", style=f"dim {Colors.YELLOW}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    console.print(Panel(
        Text("按 [q] 返回上一步", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    console.print()
    
    return input_str("请输入数字 [1-2]：")

def show_password_input_screen(ip="192.168.10.1"):
    """密码输入界面 - 必须为8位"""
    while True:
        clear_screen()

        title = "CR660X/TR660X 批量刷机模式"

        console.print(Panel(
            Text(title, style=f"bold {Colors.CYAN}"),
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
            border_style=f"{Colors.BLUE}",
            padding=(0, 2)
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
                border_style=f"{Colors.RED}",
                padding=(0, 2)
            ))
            console.print()
            input("按 [Enter] 继续...")
            continue

        return password

def show_upgrade_mode_screen():
    """CR660X 第二阶段：升级模式"""
    clear_screen()
    
    title = "CR660X/TR660X 批量刷机模式"
    
    console.print(Panel(
        Text(title, style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    
    console.print("所处模式：2 - 升级模式", style=f"{Colors.WHITE}")
    console.print()
    console.print("正在检测 192.168.1.1 上线...", style=f"{Colors.WHITE}")
    console.print()
    console.print("─" * 40, style=f"dim {Colors.WHITE}")
    console.print()
    console.print(Text(f"{Icons.LOADING} 等待openwrt initramfs启动...", style=f"bold {Colors.YELLOW}"))
    console.print()
    
    console.print(Panel(
        Text("提示：initramfs启动后通过SSH上传sysupgrade镜像", style=f"dim {Colors.YELLOW}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))

def show_flashing_screen(title="CR660X/TR660X 批量刷机模式", mode="刷机模式", step_info="正在执行系统破解脚本...", status="正在刷机..."):
    """刷机进行中（无进度条）"""
    clear_screen()

    console.print(Panel(
        Text(title, style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    
    console.print(f"所处模式：{mode}", style=f"{Colors.WHITE}")
    console.print(f"当前状态：{Icons.LOADING} {status}", style=f"{Colors.WHITE}")
    console.print()
    console.print("─" * 40, style=f"dim {Colors.WHITE}")
    console.print()
    console.print(Text(f"{Icons.LOADING} {step_info}", style=f"bold {Colors.YELLOW}"))
    console.print()

def show_success_screen(step="步骤 1/3", next_action="系统正在重启...", show_count=False, auto_wait=0):
    """刷机成功完成
    auto_wait: 自动等待秒数后返回，0表示等待按键"""
    clear_screen()
    import time

    console.print(Panel(
        Text(f"{Icons.SUCCESS} 刷机成功！", style=f"bold {Colors.GREEN}"),
        border_style=f"{Colors.GREEN}"
    ))
    console.print()

    console.print(f"已完成 {step}", style=f"{Colors.WHITE}")
    console.print()
    console.print("─" * 40, style=f"dim {Colors.WHITE}")
    console.print()

    console.print(f"下一步：{next_action}", style=f"{Colors.WHITE}")
    console.print(Text(f"{Icons.LOADING} 正在继续，请稍候...", style=f"{Colors.YELLOW}"))
    console.print()

    if show_count:
        console.print(Panel(
            Text(f"已成功刷入：{flash_count} 台", style=f"{Colors.WHITE}"),
            border_style=f"{Colors.BLUE}",
            padding=(0, 2)
        ))
        console.print()

    if auto_wait > 0:
        console.print(Panel(
            Text(f"{auto_wait} 秒后自动继续...", style=f"{Colors.YELLOW}"),
            border_style=f"{Colors.BLUE}",
            padding=(0, 2)
        ))
        console.print()
        time.sleep(auto_wait)
    else:
        console.print("按 [Enter] 继续...")
        input()

def show_fail_screen(reason="密码错误", possible_causes=None):
    """刷机失败处理"""
    if possible_causes is None:
        possible_causes = [
            "路由器密码输入错误",
            "路由器不在官方固件状态",
            "网络连接问题"
        ]
    
    clear_screen()
    
    console.print(Panel(
        Text(f"{Icons.FAIL} 刷机失败！", style=f"bold {Colors.RED}"),
        border_style=f"{Colors.RED}"
    ))
    console.print()
    
    console.print(f"失败原因：{reason}", style=f"bold {Colors.RED}")
    console.print()
    console.print("可能的原因：", style=f"{Colors.WHITE}")
    for i, cause in enumerate(possible_causes, 1):
        console.print(f"{i}. {cause}", style=f"{Colors.WHITE}")
    console.print()
    
    console.print("─" * 40, style=f"dim {Colors.WHITE}")
    console.print()
    console.print("请选择操作：", style=f"{Colors.WHITE}")
    console.print()
    console.print("[1] 查看详细日志", style=f"{Colors.WHITE}")
    console.print("[2] 重新输入密码重试", style=f"{Colors.WHITE}")
    console.print("[3] 返回主菜单", style=f"{Colors.WHITE}")
    console.print()
    
    return input_str("请输入数字 [1-3]：")

def show_jgc_step1_detecting_password(ip="192.168.10.1"):
    """JGC 步骤1 - 检测密码中"""
    clear_screen()

    console.print(Panel(
        Text("JGC Q10/Q20 路由器刷机", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()

    console.print(f"步骤 1/3：官方→PDCN", style=f"{Colors.WHITE}")
    console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
    console.print()
    console.print(Text(f"{Icons.LOADING} 正在检测密码...", style=f"bold {Colors.YELLOW}"))
    console.print()

def show_jgc_step1_password_success(ip="192.168.10.1"):
    """JGC 步骤1 - 密码检测成功"""
    clear_screen()

    console.print(Panel(
        Text("JGC Q10/Q20 路由器刷机", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()

    console.print(f"步骤 1/3：官方→PDCN", style=f"{Colors.WHITE}")
    console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
    console.print()
    console.print(Panel(
        Text("✅ 密码检测成功！（首次登录自动提供密码）", style=f"bold {Colors.GREEN}"),
        border_style=f"{Colors.GREEN}",
        padding=(0, 2)
    ))
    console.print()
    console.print(f"正在配置路由器...", style=f"{Colors.WHITE}")
    console.print()

def show_jgc_step1_password_error(ip="192.168.10.1"):
    """JGC 步骤1 - 密码错误"""
    clear_screen()

    console.print(Panel(
        Text("JGC Q10/Q20 路由器刷机", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.RED}"
    ))
    console.print()

    console.print(f"步骤 1/3：官方→PDCN", style=f"{Colors.WHITE}")
    console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
    console.print()
    console.print(Panel(
        Text("❌ 密码错误，请重新输入", style=f"bold {Colors.RED}"),
        border_style=f"{Colors.RED}",
        padding=(0, 2)
    ))
    console.print()
    console.print("输入 1 重新检测密码", style=f"{Colors.WHITE}")
    console.print()

def show_jgc_step1_password_notfound(ip="192.168.10.1"):
    """JGC 步骤1 - 未检测到密码"""
    clear_screen()

    console.print(Panel(
        Text("JGC Q10/Q20 路由器刷机", style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()

    console.print(f"步骤 1/3：官方→PDCN", style=f"{Colors.WHITE}")
    console.print(f"检测到IP：{ip}", style=f"{Colors.WHITE}")
    console.print()
    console.print(Panel(
        Text("⚠️ 未检测到密码，请输入路由器密码", style=f"bold {Colors.YELLOW}"),
        border_style=f"{Colors.YELLOW}",
        padding=(0, 2)
    ))
    console.print()
    console.print("输入 1 重新检测密码", style=f"{Colors.WHITE}")
    console.print()

def show_jgc_menu_screen():
    """JGC 主菜单"""
    clear_screen()
    
    title = "JGC Q10/Q20 路由器刷机"
    
    console.print(Panel(
        Text(title, style=f"bold {Colors.CYAN}"),
        border_style=f"{Colors.BLUE}"
    ))
    console.print()
    
    # 在线IP
    console.print(f"在线路由器：192.168.10.1", style=f"{Colors.GREEN}")
    
    # 下载服务状态
    service_status = Text("● 运行中 (123.2:8080)", style=f"bold {Colors.GREEN}")
    console.print(f"下载服务：{service_status}")
    console.print()
    
    # 选项列表
    content = Text()
    content.append("请选择刷机步骤：\n\n", style=f"bold {Colors.WHITE}")
    
    content.append("[1] 步骤 1：官方→PDCN", style=f"{Colors.WHITE}")
    content.append("       └─ 更换路由器系统\n", style=f"dim {Colors.DIM}")
    content.append("[2] 步骤 2：PDCN→引导程序", style=f"{Colors.WHITE}")
    content.append("       └─ 刷入启动引导\n", style=f"dim {Colors.DIM}")
    content.append("[3] 步骤 3：引导→最终系统", style=f"{Colors.WHITE}")
    content.append("       └─ 刷入最终系统\n", style=f"dim {Colors.DIM}")
    
    console.print(content)
    console.print()
    
    console.print(Panel(
        Text("已完成: 0 台", style=f"{Colors.WHITE}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    console.print()
    
    return input_str("请输入数字 [1-3]：")

def show_statistics_screen(total=12, this_round=3, last_device=None):
    """完成统计"""
    clear_screen()
    
    console.print(Panel(
        Text(f"{Icons.SUCCESS} 全部完成！", style=f"bold {Colors.GREEN}"),
        border_style=f"{Colors.GREEN}"
    ))
    console.print()
    
    console.print(f"已完成刷机：{total} 台", style=f"{Colors.WHITE}")
    console.print(f"本轮新增：{this_round} 台", style=f"{Colors.GREEN}")
    console.print()
    
    console.print("─" * 40, style=f"dim {Colors.WHITE}")
    console.print()
    
    console.print("库存记录已保存", style=f"{Colors.WHITE}")
    console.print()
    
    if last_device:
        console.print("最后一台：", style=f"{Colors.WHITE}")
        console.print(f"  型号：{last_device['model']}", style=f"{Colors.WHITE}")
        console.print(f"  MAC：{last_device['mac']}", style=f"{Colors.WHITE}")
        console.print(f"  时间：{last_device['time']}", style=f"{Colors.WHITE}")
        console.print()
    
    console.print(Panel(
        Text("2 秒后返回主菜单...", style=f"{Colors.YELLOW}"),
        border_style=f"{Colors.BLUE}",
        padding=(0, 2)
    ))
    
    import time
    time.sleep(2)

# ===================== 交互流程 =====================

def run_demo():
    """运行交互式Demo"""
    global flash_count
    
    while True:
        # 1. 开始界面
        choice = show_start_screen()
        
        if choice == 'q' or choice == 'Q':
            console.print("\n退出程序", style=f"{Colors.YELLOW}")
            break
        
        if choice == '1':
            # CR660X 流程 - 循环直到用户选择返回
            while True:
                # 显示刷机模式选择页面
                flow_choice = show_cr660x_main_screen()
                
                if flow_choice == 'q' or flow_choice == 'Q':
                    break  # 返回主菜单
                
                if flow_choice == '1':
                    # 官方系统破解刷入BOOTLOADER和KERNEL
                    # 需要选择运营商
                    carrier_choice = show_cr660x_carrier_screen()
                    
                    if carrier_choice == 'q' or carrier_choice == 'Q':
                        continue
                    
                    if carrier_choice == '1':
                        # 移动/电信 - 需要密码
                        password = show_password_input_screen()
                        
                        if password == 'q' or password == 'Q':
                            continue
                        
                        # 模拟刷机中 - 第一阶段
                        show_flashing_screen(
                            mode="1 - 刷机模式",
                            step_info="正在执行系统破解脚本...",
                            status="正在刷入BOOTLOADER和KERNEL..."
                        )
                        import time
                        time.sleep(2)

                        # 第一阶段成功，自动进入第二阶段（5秒后自动跳转）
                        show_success_screen(
                            step="第一阶段（刷机模式）",
                            next_action="自动进入第二阶段（升级模式）",
                            auto_wait=5
                        )

                        # 第二阶段：升级模式
                        show_upgrade_mode_screen()
                        time.sleep(2)

                        # 第二阶段完成 - 记录MAC并计数
                        new_mac = "aa:bb:cc:dd:ee:01"  # 模拟MAC地址
                        if record_mac_to_file(new_mac, "CR660X"):
                            show_success_screen(
                                step="第二阶段（升级模式）",
                                next_action="系统升级完成，库存记录已保存",
                                show_count=True
                            )
                        else:
                            # MAC已存在，不计数
                            show_success_screen(
                                step="第二阶段（升级模式）",
                                next_action="系统升级完成（该设备已记录）",
                                show_count=True
                            )
                        
                    elif carrier_choice == '2':
                        # 联通 - 自动，不需要密码
                        show_flashing_screen(
                            mode="1 - 刷机模式",
                            step_info="正在执行系统破解脚本...",
                            status="正在刷机（联通版本）..."
                        )
                        import time
                        time.sleep(2)
                        
                        # 第一阶段成功，自动进入第二阶段（5秒后自动跳转）
                        show_success_screen(
                            step="第一阶段（刷机模式）",
                            next_action="自动进入第二阶段（升级模式）",
                            auto_wait=5
                        )

                        # 第二阶段：升级模式
                        show_upgrade_mode_screen()
                        time.sleep(2)

                        # 第二阶段完成 - 记录MAC并计数
                        new_mac = "aa:bb:cc:dd:ee:02"  # 模拟MAC地址
                        if record_mac_to_file(new_mac, "CR660X"):
                            show_success_screen(
                                step="第二阶段（升级模式）",
                                next_action="系统升级完成，库存记录已保存",
                                show_count=True
                            )
                        else:
                            show_success_screen(
                                step="第二阶段（升级模式）",
                                next_action="系统升级完成（该设备已记录）",
                                show_count=True
                            )
                    
                elif flow_choice == '2':
                    # OPENWRT升级自定义固件
                    show_upgrade_mode_screen()
                    import time
                    time.sleep(2)
                    
                    # 升级完成 - 记录MAC并计数
                    new_mac = "aa:bb:cc:dd:ee:03"  # 模拟MAC地址
                    if record_mac_to_file(new_mac, "CR660X"):
                        show_success_screen(
                            step="升级模式",
                            next_action="系统升级完成，库存记录已保存",
                            show_count=True
                        )
                    else:
                        show_success_screen(
                            step="升级模式",
                            next_action="系统升级完成（该设备已记录）",
                            show_count=True
                        )
            
        elif choice == '2':
            # JGC 流程 - 步骤1→2→3 自动串联
            while True:
                step_choice = show_jgc_menu_screen()

                if step_choice == 'q' or step_choice == 'Q':
                    break  # 返回主菜单

                if step_choice == '1':
                    # 步骤 1：官方→PDCN（带密码检测）
                    # 模拟密码检测流程
                    show_jgc_step1_detecting_password()
                    import time
                    time.sleep(2)

                    # 模拟：密码检测成功（首次自动提供密码）
                    show_jgc_step1_password_success()
                    time.sleep(2)

                    # 正在刷入PDCN
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 1/3：官方→PDCN",
                        status="正在刷入PDCN系统..."
                    )

                    # 步骤1成功，自动进入步骤2
                    show_success_screen(
                        step="步骤 1/3",
                        next_action="即将自动进入步骤 2...",
                        auto_wait=5
                    )

                    # 步骤 2：PDCN→引导程序
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 2/3：PDCN→引导程序",
                        status="正在刷入引导程序..."
                    )
                    time.sleep(2)

                    # 步骤2成功，自动进入步骤3
                    show_success_screen(
                        step="步骤 2/3",
                        next_action="即将自动进入步骤 3...",
                        auto_wait=5
                    )

                    # 步骤 3：引导→最终系统
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 3/3：引导→最终系统",
                        status="正在刷入最终系统..."
                    )
                    time.sleep(2)

                    # 完成 - 记录MAC并计数
                    new_mac = "aa:bb:cc:dd:ee:ff"
                    if record_mac_to_file(new_mac, "JGC-Q10"):
                        show_statistics_screen(
                            total=flash_count,
                            this_round=1,
                            last_device={
                                "model": "JGC-Q10",
                                "mac": new_mac,
                                "time": "2026-05-09 15:30"
                            }
                        )
                    else:
                        show_success_screen(
                            step="步骤 3/3",
                            next_action="刷入完成（该设备已记录）",
                            show_count=True
                        )

                elif step_choice == '2':
                    # 步骤 2：PDCN→引导程序（直接从步骤2开始）
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 2/3：PDCN→引导程序",
                        status="正在刷入引导程序..."
                    )
                    import time
                    time.sleep(2)

                    # 步骤2成功，自动进入步骤3
                    show_success_screen(
                        step="步骤 2/3",
                        next_action="即将自动进入步骤 3...",
                        auto_wait=5
                    )

                    # 步骤 3：引导→最终系统
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 3/3：引导→最终系统",
                        status="正在刷入最终系统..."
                    )
                    time.sleep(2)

                    # 完成 - 记录MAC并计数
                    new_mac = "aa:bb:cc:dd:ee:ff"
                    if record_mac_to_file(new_mac, "JGC-Q10"):
                        show_statistics_screen(
                            total=flash_count,
                            this_round=1,
                            last_device={
                                "model": "JGC-Q10",
                                "mac": new_mac,
                                "time": "2026-05-09 15:30"
                            }
                        )
                    else:
                        show_success_screen(
                            step="步骤 3/3",
                            next_action="刷入完成（该设备已记录）",
                            show_count=True
                        )

                elif step_choice == '3':
                    # 步骤 3：引导→最终系统（直接刷步骤3）
                    show_flashing_screen(
                        title="JGC Q10/Q20 路由器刷机",
                        step_info="步骤 3/3：引导→最终系统",
                        status="正在刷入最终系统..."
                    )
                    import time
                    time.sleep(2)

                    # 完成 - 记录MAC并计数
                    new_mac = "aa:bb:cc:dd:ee:ff"
                    if record_mac_to_file(new_mac, "JGC-Q10"):
                        show_statistics_screen(
                            total=flash_count,
                            this_round=1,
                            last_device={
                                "model": "JGC-Q10",
                                "mac": new_mac,
                                "time": "2026-05-09 15:30"
                            }
                        )
                    else:
                        show_success_screen(
                            step="步骤 3/3",
                            next_action="刷入完成（该设备已记录）",
                            show_count=True
                        )
        
        else:
            console.print("\n无效输入，请重新选择", style=f"{Colors.RED}")
            import time
            time.sleep(1)

if __name__ == "__main__":
    console.print("\n" + "=" * 50, style=f"bold {Colors.CYAN}")
    console.print("路由器刷机工具 TUI Demo", style=f"bold {Colors.CYAN}")
    console.print("=" * 50 + "\n", style=f"bold {Colors.CYAN}")
    console.print("说明：", style=f"{Colors.WHITE}")
    console.print("- 这是界面交互演示，不会真实刷机", style=f"{Colors.WHITE}")
    console.print("- 按 q 或 Q 可以返回上级或退出", style=f"{Colors.WHITE}")
    console.print("- 输入数字选择选项\n", style=f"{Colors.WHITE}")
    
    input("按 [Enter] 开始...")
    
    run_demo()
