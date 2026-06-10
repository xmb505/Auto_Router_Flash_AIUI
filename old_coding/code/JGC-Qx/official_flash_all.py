#!/usr/bin/env python3
import subprocess
import time
import sys
import os

def ping_router(ip="192.168.2.1"):
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

def get_password():
    """获取路由器密码"""
    print("正在尝试自动获取路由器默认密码...")
    password = run_script('get_passwd.py')
    
    if password and password != "null" and password.lower() != "none":
        print(f"成功获取默认密码: {password}")
        return password
    else:
        print("自动获取密码失败，请手动输入路由器密码:")
        password = input().strip()
        while not password:
            print("密码不能为空，请重新输入:")
            password = input().strip()
        return password

def get_stok_sysauth(password):
    """获取stok和sysauth"""
    print("正在获取认证信息...")
    result = run_script('get_stok.py', password)
    
    if not result:
        return None, None
    
    # 解析输出获取stok和sysauth
    stok = None
    sysauth = None
    
    for line in result.split('\n'):
        if line.startswith('stok='):
            stok = line.split('=', 1)[1]
        elif line.startswith('sysauth='):
            sysauth = line.split('=', 1)[1]
    
    return stok, sysauth

def upload_firmware(stok, sysauth):
    """上传固件"""
    print("正在上传固件...")
    result = run_script('put_firmware.py', stok, sysauth)
    # 检查输出中是否包含"OK"，因为可能有中文提示信息
    if result and "OK" in result:
        return True
    return False

def confirm_upgrade(stok, sysauth):
    """确认升级"""
    print("正在确认固件升级...")
    result = run_script('confirm_upgrade.py', stok, sysauth)
    # 检查输出中是否包含"OK"，因为可能有中文提示信息
    if result and "OK" in result:
        return True
    return False

def wait_for_router_reboot():
    """等待路由器重启完成"""
    print("等待路由器重启...")
    time.sleep(10)
    
    # 等待路由器重新上线
    print("等待路由器重新上线...")
    max_wait = 60  # 最多等待60秒
    wait_count = 0
    
    while wait_count < max_wait:
        if ping_router():
            print("路由器已重新上线")
            return True
        time.sleep(1)
        wait_count += 1
    
    print("等待路由器上线超时")
    return False

def main():
    """主函数"""
    print("=== JCG路由器官方固件刷机工具 ===")
    
    print("\n开始刷机流程...")
    
    # 1. 检测路由器是否在线
    print("正在检测路由器是否在线...")
    if not ping_router():
        print("路由器不在线，请检查连接后重新运行脚本...")
        return
    
    # 2. 获取密码
    password = get_password()
    if not password or password == "null":
        print("未能获取有效密码，刷机流程中断")
        return
    
    # 3. 获取stok和sysauth
    stok, sysauth = get_stok_sysauth(password)
    
    if not stok or stok == "null" or not sysauth or sysauth == "null":
        print("密码错误，请检查密码是否输入正确，或者恢复出厂设置，如果已知错误请检查脚本是否有问题")
        return
    
    print(f"成功获取认证信息: stok={stok}, sysauth={sysauth}")
    
    # 4. 上传固件
    if not upload_firmware(stok, sysauth):
        print("固件上传失败，刷机流程中断")
        return
    
    print("固件上传成功")
    
    # 5. 确认升级
    if not confirm_upgrade(stok, sysauth):
        print("确认升级失败，刷机流程中断")
        return
    
    print("确认升级成功")
    
    # 6. 等待重启
    if not wait_for_router_reboot():
        print("路由器重启后未能正常上线，刷机流程可能失败")
        return
    
    print("刷机流程完成，脚本退出")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n刷机流程被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"刷机流程出错: {e}")
        sys.exit(1)