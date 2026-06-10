#!/usr/bin/env python3
import subprocess
import time
import sys

def ping_router(ip="192.168.123.1"):
    """检测路由器是否在线"""
    try:
        result = subprocess.run(['ping', '-c', '1', ip], 
                              stdout=subprocess.DEVNULL, 
                              stderr=subprocess.DEVNULL,
                              timeout=3)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False

def run_script(script_name, *args):
    """运行指定的Python脚本并返回输出"""
    try:
        cmd = ['python3', script_name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"运行 {script_name} 超时")
        return None
    except Exception as e:
        print(f"运行 {script_name} 出错: {e}")
        return None

def main():
    """主函数"""
    print("=== PDCN系统bootloader刷入工具 ===")
    
    while True:
        print("\n开始新的刷机流程...")
        
        # 1. 检测路由器是否在线
        print("正在检测路由器是否在线...")
        if not ping_router():
            print("路由器不在线，请检查连接后按回车重试...")
            input()
            continue
        
        # 2. 上传bootloader
        print("正在上传bootloader...")
        result = run_script('pdcn_put_bootloader.py')
        if not result:
            print("上传bootloader失败，刷机流程中断")
            continue
        
        print("bootloader上传成功")
        
        # 3. 刷入bootloader
        print("正在刷入bootloader...")
        result = run_script('pdcn_flash_bootloader.py')
        if not result:
            print("刷入bootloader失败，刷机流程中断")
            continue
        
        print("bootloader刷入成功")
        
        # 4. 重启路由器
        print("正在重启路由器...")
        result = run_script('pdcn_reboot.py')
        if not result:
            print("重启命令发送失败，但可能已重启")
        
        print("重启命令已发送")
        
        # 5. 等待10秒
        print("等待10秒...")
        time.sleep(10)
        
        print("刷机流程完成，准备开始下一轮...")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n刷机流程被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"刷机流程出错: {e}")
        sys.exit(1)