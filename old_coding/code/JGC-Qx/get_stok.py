#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import base64
import sys
import re
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

def get_stok(password):
    """
    登录路由器并获取stok
    """
    try:
        # Base64编码用户名和密码
        username_encoded = base64.b64encode(b"root").decode('utf-8')
        password_encoded = base64.b64encode(password.encode('utf-8')).decode('utf-8')
        
        # 登录数据
        login_data = {
            'username': username_encoded,
            'pc_mac': '00:0E:C6:34:2F:5A',
            'password': password_encoded
        }
        
        # 发送POST请求
        response = requests.post(
            'http://192.168.2.1/cgi-bin/luci',
            data=login_data,
            timeout=10,
            allow_redirects=False  # 不自动跟随重定向
        )
        
        # 检查是否有重定向
        if response.status_code == 302:
            # 从Location头部提取stok
            location = response.headers.get('Location', '')
            stok_match = re.search(r'stok=([a-f0-9]+)', location)
            stok = stok_match.group(1) if stok_match else None
            
            # 从Set-Cookie头部提取sysauth
            set_cookie = response.headers.get('Set-Cookie', '')
            sysauth_match = re.search(r'sysauth=([a-f0-9]+)', set_cookie)
            sysauth = sysauth_match.group(1) if sysauth_match else None
            
            # 返回stok和sysauth
            if stok and sysauth:
                return stok, sysauth
        
        return None, None
    except Exception as e:
        print(f"获取stok时出错: {e}", file=sys.stderr)
        return None

def main():
    """
    主函数
    """
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("用法: ./get_stok.py <密码>", file=sys.stderr)
        sys.exit(1)
    
    # 获取密码
    password = sys.argv[1]
    
    # 获取stok和sysauth
    stok, sysauth = get_stok(password)
    
    # 打印stok和sysauth
    if stok and sysauth:
        print(f"stok={stok}")
        print(f"sysauth={sysauth}")
    else:
        print("stok=null")
        print("sysauth=null")

if __name__ == "__main__":
    main()