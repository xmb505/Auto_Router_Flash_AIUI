#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import sys
import os
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# 固件文件路径
FIRMWARE_PATH = "./image/JCG-Q20-PDCN.bin"

def upload_firmware(stok, sysauth):
    """
    上传固件到路由器
    """
    try:
        # 检查固件文件是否存在
        if not os.path.exists(FIRMWARE_PATH):
            print(f"固件文件不存在: {FIRMWARE_PATH}", file=sys.stderr)
            return False
        
        # 构造URL
        url = f'http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/upload_firmware'
        
        # 设置请求头部
        headers = {
            'Referer': f'http://192.168.2.1/cgi-bin/luci/;stok={stok}/rnt/advanceSetup/update',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'http://192.168.2.1',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
        }
        
        # 设置Cookie
        cookies = {
            'sysauth': sysauth
        }
        
        # 准备文件数据
        with open(FIRMWARE_PATH, 'rb') as f:
            files = {
                'image': ('JCG-Q20-PDCN.bin', f, 'application/octet-stream')
            }
            
            # 发送POST请求
            response = requests.post(url, headers=headers, cookies=cookies, files=files, timeout=60)
        
        # 检查响应状态码
        if response.status_code == 200:
            # 解析响应JSON
            result = response.json()
            if result.get("code") == 0:
                return True
            else:
                print(f"固件上传失败: {result}", file=sys.stderr)
                return False
        else:
            print(f"HTTP状态码: {response.status_code}", file=sys.stderr)
            print(f"响应内容: {response.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"上传固件时出错: {e}", file=sys.stderr)
        return False

def check_firmware(stok, sysauth):
    """
    检查固件是否验证成功
    """
    try:
        # 构造URL
        url = f'http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/check_firmware'
        
        # 设置请求头部
        headers = {
            'Referer': f'http://192.168.2.1/cgi-bin/luci/;stok={stok}/rnt/advanceSetup/update',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
        }
        
        # 设置Cookie
        cookies = {
            'sysauth': sysauth
        }
        
        # 发送GET请求
        response = requests.get(url, headers=headers, cookies=cookies, timeout=20)
        
        # 检查响应状态码
        if response.status_code == 200:
            # 解析响应JSON
            result = response.json()
            
            # 检查固件验证是否成功
            if (result.get("support") == True and 
                result.get("size_correct") == True and 
                result.get("file_exists") == True):
                return True
            else:
                print(f"固件验证失败: {result}", file=sys.stderr)
                return False
        else:
            print(f"HTTP状态码: {response.status_code}", file=sys.stderr)
            print(f"响应内容: {response.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"检查固件时出错: {e}", file=sys.stderr)
        return False

def main():
    """
    主函数
    """
    # 检查命令行参数
    if len(sys.argv) != 3:
        print("用法: ./put_firmware.py <stok> <sysauth>", file=sys.stderr)
        sys.exit(1)
    
    # 获取参数
    stok = sys.argv[1]
    sysauth = sys.argv[2]
    
    # 上传固件
    print("正在上传固件...")
    upload_success = upload_firmware(stok, sysauth)
    
    if not upload_success:
        print("null")
        return
    
    # 检查固件
    print("正在验证固件...")
    check_success = check_firmware(stok, sysauth)
    
    # 打印结果
    if check_success:
        print("OK")
    else:
        print("null")

if __name__ == "__main__":
    main()