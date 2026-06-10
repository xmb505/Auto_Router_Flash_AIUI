#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由器批量刷机平台 — 统一入口
融合 CR660X / JGC / AX3000T / AX3600 / AX5 / AX6 / xmir-patcher
"""

import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent

def clear():
    os.system('clear')

def print_header():
    print("=" * 54)
    print("  路由器批量刷机平台 - 统一入口 (Router Flash Platform)")
    print("=" * 54)
    print()

def print_menu():
    print("  请选择路由器型号/工具：")
    print()
    print("  ┌─────────────────────────────────────────────┐")
    print("  │  [1]  CR660X 系列 (小米/联通定制版)        │")
    print("  │  [2]  JGC Q10/Q20 系列                     │")
    print("  │  [3]  AX3000T (小米/Redmi)                 │")
    print("  │  [4]  AX3600 (小米)                        │")
    print("  │  [5]  AX5 (Redmi)                          │")
    print("  │  [6]  AX6 (Redmi)                          │")
    print("  │  [7]  xmir-patcher (通用小米路由器工具)     │")
    print("  │  [8]  HTTP 服务器 (chfs)                   │")
    print("  │  [h]  帮助信息                             │")
    print("  │  [q]  退出                                  │")
    print("  └─────────────────────────────────────────────┘")
    print()

def print_help():
    clear()
    print_header()
    print("  📖 帮助信息")
    print("  " + "-" * 50)
    print()
    print("  1. CR660X — 小米/联通定制版路由器刷机")
    print("     使用 TUI 交互界面，支持三阶段刷机")
    print("     (需要安装 rich, scapy, requests)")
    print()
    print("  2. JGC Q10/Q20 — JGC 系列路由器刷机")
    print("     使用 TUI 交互界面，支持三阶段刷机")
    print("     (需要安装 rich, scapy, requests)")
    print()
    print("  3. AX3000T — 小米/Redmi AX3000T 刷机")
    print("     使用 TUI 交互界面，支持三阶段刷机")
    print()
    print("  4. AX3600 — 小米 AX3600 刷机")
    print("     使用 TUI 交互界面，支持四阶段刷机")
    print()
    print("  5. AX5 — Redmi AX5 刷机")
    print("     支持: 开启SSH -> 刷写mibib/uboot -> 刷写固件")
    print()
    print("  6. AX6 — Redmi AX6 刷机")
    print("     支持: 开启SSH -> 刷写uboot -> 刷写固件")
    print()
    print("  7. xmir-patcher — 通用小米路由器补丁/刷机工具")
    print("     支持多型号路由器 SSH 开启、Bootloader 刷写等")
    print()
    print("  8. HTTP 服务器 — 内置 chfs HTTP 文件服务器")
    print("     用于路由器从服务器下载固件")
    print()
    input("  按 Enter 返回主菜单...")

def launch_tui():
    """启动 TUI 交互界面（支持 CR660X / JGC / AX3000T）"""
    sys.path.insert(0, str(ROOT))
    from main import main
    main()

def launch_ax_model(model_dir):
    """进入某个 AX 型号的目录，显示该型号可用脚本"""
    clear()
    model_path = ROOT / model_dir
    print_header()
    print(f"  型号: {model_dir}")
    print("  " + "-" * 50)
    print()
    
    scripts = sorted([f for f in os.listdir(model_path) 
                      if f.endswith(('.py', '.sh')) and f != '__init__.py'])
    
    print(f"  可用脚本 ({len(scripts)} 个):")
    print()
    for i, script in enumerate(scripts, 1):
        print(f"  [{i}] {script}")
    print()
    print("  [r] 返回主菜单")
    print("  [q] 退出")
    print()
    
    choice = input("  请选择 [1-{}]: ".format(len(scripts))).strip()
    
    if choice.lower() == 'r':
        return
    if choice.lower() == 'q':
        sys.exit(0)
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(scripts):
            script = scripts[idx]
            full_path = model_path / script
            os.chdir(str(model_path))
            
            if script.endswith('.py'):
                os.system(f'python3 "{full_path}"')
            elif script.endswith('.sh'):
                os.system(f'bash "{full_path}"')
            
            input("\n  脚本执行完毕，按 Enter 返回...")
    except (ValueError, IndexError):
        pass

def launch_xmir_patcher():
    """启动 xmir-patcher"""
    clear()
    xmir_path = ROOT / 'xmir-patcher'
    os.chdir(str(xmir_path))
    os.system('python3 menu.py')
    input("\n  按 Enter 返回主菜单...")

def launch_httpserver():
    """启动 HTTP 文件服务器"""
    clear()
    print_header()
    print("  HTTP 文件服务器 (chfs)")
    print("  " + "-" * 50)
    print()
    print("  请选择端口 (默认 8080): ", end='')
    port = input().strip() or '8080'
    
    chfs_path = ROOT / 'httpserver' / 'chfs'
    if chfs_path.exists():
        os.chdir(str(ROOT))
        print(f"\n  启动 HTTP 服务器于端口 {port}...")
        print("  按 Ctrl+C 停止服务器")
        print()
        os.system(f'chmod +x "{chfs_path}" && "{chfs_path}" --port={port} --path="."')
    else:
        print("  chfs 文件不存在！")
        input("\n  按 Enter 返回...")

def main():
    while True:
        clear()
        print_header()
        print_menu()
        
        choice = input("  请输入数字: ").strip().lower()
        
        if choice == 'q':
            print("\n  再见！")
            break
        
        elif choice == '1':
            launch_tui()

        elif choice == '2':
            launch_tui()  # JGC 也是同一个 TUI

        elif choice == '3':
            launch_tui()  # TUI 已支持 AX3000T

        elif choice == '4':
            launch_tui()  # TUI 已支持 AX3600

        elif choice == '5':
            launch_ax_model('ax5')
            launch_ax_model('ax5')
        
        elif choice == '6':
            launch_tui()  # TUI 已支持 AX6
        
        elif choice == '7':
            launch_xmir_patcher()
        
        elif choice == '8':
            launch_httpserver()
        
        elif choice == 'h':
            print_help()
        
        else:
            print("\n  无效输入，请重新选择")
            input("  按 Enter 继续...")

if __name__ == '__main__':
    main()
