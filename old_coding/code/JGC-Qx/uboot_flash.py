#!/usr/bin/env python3
import requests
import time
import os
import re

def wait_for_router_online():
    """等待路由器在线"""
    import subprocess
    while True:
        try:
            # 使用ping检测路由器是否在线
            result = subprocess.run(['ping', '-c', '1', '192.168.1.1'], 
                                  stdout=subprocess.DEVNULL, 
                                  stderr=subprocess.DEVNULL,
                                  timeout=3)
            if result.returncode == 0:
                print("路由器已在线")
                return True
            else:
                print("路由器不在线，等待3秒...")
                time.sleep(3)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            print("路由器不在线，等待3秒...")
            time.sleep(3)

def upload_firmware():
    """上传固件文件"""
    firmware_path = './image/sharewifi_jqg_q20_1.1.bin'
    
    if not os.path.exists(firmware_path):
        print(f"固件文件不存在: {firmware_path}")
        return False
    
    # 构造multipart/form-data数据
    boundary = '----WebKitFormBoundarybqaq1PRB1QT3aVhC'
    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}'
    }
    
    # 读取固件文件
    with open(firmware_path, 'rb') as f:
        firmware_data = f.read()
    
    # 构造POST数据
    post_data = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="firmware"; filename="sharewifi_jqg_q20_1.1.bin"\r\n'
        f'Content-Type: application/octet-stream\r\n'
        f'\r\n'
    ).encode('utf-8') + firmware_data + (
        f'\r\n--{boundary}--\r\n'
    ).encode('utf-8')
    
    try:
        print("正在上传固件...")
        response = requests.post(
            'http://192.168.1.1/upload.cgi',
            data=post_data,
            headers=headers,
            timeout=30
        )
        
        # 检查响应中是否包含successfully uploaded，即使响应异常
        if 'successfully uploaded' in response.text.lower() or 'upload' in response.text.lower():
            print("固件上传成功")
            return True
        else:
            print(f"固件上传失败，响应内容: {response.text[:200]}")
            return False
            
    except requests.exceptions.RequestException as e:
        # 特别处理BadStatusLine异常，uboot的httpd响应可能不标准
        if 'successfully uploaded' in str(e).lower() or 'upload' in str(e).lower():
            print("固件上传成功")
            return True
        else:
            print(f"上传固件时出错: {e}")
            return False

def check_status():
    """检查刷机状态"""
    max_retries = 60  # 最多等待5分钟
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            response = requests.get('http://192.168.1.1/status.html', timeout=5)
            
            # 解析状态响应
            status_text = response.text.strip()
            print(f"状态响应: {status_text}")
            
            # 使用正则表达式提取状态和进度
            status_match = re.search(r'"status":"([^"]+)"', status_text)
            progress_match = re.search(r'"progress":"([^"]+)"', status_text)
            
            if status_match and progress_match:
                status = status_match.group(1)
                progress = progress_match.group(1)
                
                print(f"刷机状态: {status}, 进度: {progress}%")
                
                # 检查是否完成
                if status.lower() == 'done' and progress == '100':
                    print("刷机完成，准备重启...")
                    return True
                
            time.sleep(2)
            retry_count += 1
            
        except requests.exceptions.RequestException as e:
            # 特别处理BadStatusLine异常，uboot的httpd响应可能不标准
            error_str = str(e)
            if 'status:"done"' in error_str and 'progress:"100"' in error_str:
                print("刷机完成，准备重启...")
                return True
            elif 'status:"' in error_str and 'progress:"' in error_str:
                # 从错误信息中提取状态
                status_match = re.search(r'status:"([^"]+)"', error_str)
                progress_match = re.search(r'progress:"([^"]+)"', error_str)
                
                if status_match and progress_match:
                    status = status_match.group(1)
                    progress = progress_match.group(1)
                    
                    print(f"刷机状态: {status}, 进度: {progress}%")
                    
                    # 检查是否完成
                    if status.lower() == 'done' and progress == '100':
                        print("刷机完成，准备重启...")
                        return True
                
                time.sleep(2)
                retry_count += 1
            else:
                print(f"检查状态时出错: {e}")
                time.sleep(2)
                retry_count += 1
    
    print("检查状态超时")
    return False

def reboot_router():
    """重启路由器"""
    try:
        response = requests.get('http://192.168.1.1/reboot.cgi', timeout=5)
        print("刷机完成，重启中...")
        return True
    except requests.exceptions.RequestException as e:
        print(f"重启命令已发送 (uboot的httpd可能不会返回标准响应)")
        print("刷机完成，重启中...")
        return True

def main():
    """主函数"""
    while True:
        print("=== 开始新的刷机循环 ===")
        
        # 1. 等待路由器在线
        wait_for_router_online()
        
        # 2. 上传固件
        if not upload_firmware():
            print("固件上传失败，重新开始循环...")
            time.sleep(5)
            continue
        
        # 3. 检查刷机状态
        if not check_status():
            print("刷机状态检查失败，重新开始循环...")
            time.sleep(5)
            continue
        
        # 4. 重启路由器
        reboot_router()
        
        # 5. 等待一段时间再开始下一个循环
        print("等待5秒后开始下一个刷机循环...")
        time.sleep(5)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n脚本被用户中断")
    except Exception as e:
        print(f"脚本执行出错: {e}")
