#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import sys
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

def set_wan_mode(stok, sysauth):
    """
    设置路由器WAN口为DHCP模式
    """
    try:
        # 构造URL
        url = f'http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGnetwork/firstSetup_wan'
        
        # POST数据
        payload = {
            'wanTypeSelect': 'dhcp',
            'username': '',
            'password': '',
            'ipaddr': '',
            'gateway': '',
            'dns1': '',
            'dns2': ''
        }
        
        # 设置请求头部
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Referer': f'http://192.168.2.1/cgi-bin/luci/;stok={stok}',
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
        
        # 发送POST请求
        response = requests.post(url, data=payload, headers=headers, cookies=cookies, timeout=10)
        
        # 检查响应状态码
        if response.status_code == 200:
            return True
        else:
            print(f"HTTP状态码: {response.status_code}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"设置WAN模式时出错: {e}", file=sys.stderr)
        return False

def main():
    """
    主函数
    """
    # 检查命令行参数
    if len(sys.argv) != 3:
        print("用法: ./set_wan_mode.py <stok> <sysauth>", file=sys.stderr)
        sys.exit(1)
    
    # 获取stok和sysauth
    stok = sys.argv[1]
    sysauth = sys.argv[2]
    
    # 设置WAN模式
    success = set_wan_mode(stok, sysauth)
    
    # 打印结果
    if success:
        print("OK")
    else:
        print("null")

if __name__ == "__main__":
    main()

