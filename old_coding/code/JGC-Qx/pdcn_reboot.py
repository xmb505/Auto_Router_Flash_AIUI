#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import sys
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# 默认IP地址
DEFAULT_IP = "192.168.123.1"

# Basic认证信息 (admin:admin)
AUTHORIZATION = "Basic YWRtaW46YWRtaW4="

def reboot_router(ip_address):
    """
    重启路由器并返回执行结果
    """
    try:
        # 构造URL
        url = f'http://{ip_address}/apply.cgi'
        
        # POST数据
        payload = {
            'action_mode': ' SystemCmd ',
            'current_page': 'console_response.asp',
            'next_page': 'console_response.asp',
            'SystemCmd': 'reboot'
        }
        
        # 设置请求头部
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Authorization': AUTHORIZATION,
            'Referer': f'http://{ip_address}/Advanced_Console_Content.asp',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': f'http://{ip_address}',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
        }
        
        # 发送POST请求执行命令
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        
        # 检查POST请求是否成功
        if response.status_code == 200:
            # 获取命令执行结果
            return get_command_result(ip_address)
        else:
            print(f"HTTP状态码: {response.status_code}", file=sys.stderr)
            print(f"响应内容: {response.text}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"重启路由器时出错: {e}", file=sys.stderr)
        return None

def get_command_result(ip_address):
    """
    获取命令执行结果
    """
    try:
        # 构造获取结果的URL
        url = f'http://{ip_address}/console_response.asp'
        
        # 设置请求头部
        headers = {
            'Authorization': AUTHORIZATION,
            'Referer': f'http://{ip_address}/Advanced_Console_Content.asp',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
        }
        
        # 发送GET请求获取结果
        response = requests.get(url, headers=headers, timeout=30)
        
        # 检查响应状态码
        if response.status_code == 200:
            return response.text
        else:
            print(f"获取命令结果时HTTP状态码: {response.status_code}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"获取命令结果时出错: {e}", file=sys.stderr)
        return None

def main():
    """
    主函数
    """
    # 从命令行参数获取IP地址，如果没有提供则使用默认IP
    ip_address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IP
    
    # 重启路由器并获取结果
    result = reboot_router(ip_address)
    
    # 打印结果
    if result is not None:
        print(result)
    else:
        print("null")

if __name__ == "__main__":
    main()