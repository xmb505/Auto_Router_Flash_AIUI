#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import sys
from urllib3.exceptions import InsecureRequestWarning

# 禁用SSL警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

def cancel_upgrade(stok, sysauth):
    """
    取消路由器固件升级
    """
    try:
        # 构造URL
        url = f'http://192.168.10.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/download_firmware_cancel'
        
        # 设置请求头部
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
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
            
            # 检查返回码
            if result.get("code") == 0:
                return True
            else:
                print(f"取消升级失败: {result}", file=sys.stderr)
                return False
        else:
            print(f"HTTP状态码: {response.status_code}", file=sys.stderr)
            print(f"响应内容: {response.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"取消升级时出错: {e}", file=sys.stderr)
        return False

def main():
    """
    主函数
    """
    # 检查命令行参数
    if len(sys.argv) != 3:
        print("用法: ./cancel_upgrade.py <stok> <sysauth>", file=sys.stderr)
        sys.exit(1)
    
    # 获取参数
    stok = sys.argv[1]
    sysauth = sys.argv[2]
    
    # 取消升级
    success = cancel_upgrade(stok, sysauth)
    
    # 打印结果
    if success:
        print("OK")
    else:
        print("null")

if __name__ == "__main__":
    main()