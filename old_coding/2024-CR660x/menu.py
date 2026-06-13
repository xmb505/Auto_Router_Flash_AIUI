#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess

import xmir_base
import gateway
from gateway import die


gw = gateway.Gateway(detect_device = False, detect_ssh = False)

def get_header(delim, suffix = ''):
  header = delim*58 + '\n'
  header += '\n'
  header += '小米CR660X系列路由器刷机工具 {} \n'.format(suffix)
  header += '\n'
  return header

def menu1_show():
  gw.load_config()
  print(get_header('='))
  print(' 1 - 设置IP地址 (当前值为: {})'.format(gw.ip_addr))
  print(' 2 - 连接到设备 (开启SSH)')
  print(' 3 - 读取完整的设备信息')
  print(' 4 - 创建完整备份')
  print(' 5 - 安装EN/RU语言')
  print(' 6 - 刷入pb-boot')
  #print(' 7 - 刷入固件 (从 "firmware" 目录)')
  print(' 8 - {{{ 其他功能 }}}')
  print(' 9 - [[ 重新启动设备 ]]')
  print(' 0 - 退出')

def menu1_process(id):
  if id == 1: 
    ip_addr = input("输入路由器IP地址: ")
    return [ "gateway.py", ip_addr ]
  if id == 2: return "connect.py"
  if id == 3: return "read_info.py"
  if id == 4: return "create_backup.py"
  if id == 5: return "install_lang.py"
  if id == 6: return [ "install_bl.py", "breed" ]
  if id == 7: return "install_fw.py"
  if id == 8: return "__menu2"
  if id == 9: return "reboot.py"
  if id == 0: sys.exit(0)
  return None

def menu2_show():
  print(get_header('-', '(扩展功能)'))
  #print(' 1 - 设置默认设备IP地址')
  print(' 2 - 更改root密码')
  print(' 3 - 读取dmesg和系统日志')
  print(' 4 - 创建指定分区的备份')
  print(' 5 - 卸载 EN/RU 语言')
  #print(' 6 - 设置内核引导地址')
  print(' 7 - 安装永久 SSH')
  #print(' 8 - __试验__')
  print(' 9 - [[ 重新启动设备 ]]')
  print(' 0 - 返回到主菜单')

def menu2_process(id):
  if id == 1: return "set_def_ipaddr.by"
  if id == 2: return "passw.py"
  if id == 3: return "read_dmesg.py"
  if id == 4: return [ "create_backup.py", "part" ]
  if id == 5: return [ "install_lang.py", "uninstall" ]
  if id == 6: return "activate_boot.py"
  if id == 7: return "install_ssh.py"
  if id == 8: return "test.py"
  if id == 9: return "reboot.py"
  if id == 0: return "__menu1" 
  return None

def menu_show(level):
  if level == 1:
    menu1_show()
    return '选择: '
  else:
    menu2_show()
    return '选择: '

def menu_process(level, id):
  if level == 1:
    return menu1_process(id)
  else:
    return menu2_process(id)

def menu():
  level = 1
  while True:
    print('')
    prompt = menu_show(level)
    print('')
    select = input(prompt)
    print('')
    if not select:
      continue
    try:
      id = int(select)
    except Exception:
      id = -1
    if id < 0:
      continue
    cmd = menu_process(level, id)
    if not cmd:
      continue
    if cmd == '__menu1':
      level = 1
      continue
    if cmd == '__menu2':
      level = 2
      continue
    #print("cmd2 =", cmd)
    if isinstance(cmd, str):
      result = subprocess.run([sys.executable, cmd])
    else:  
      result = subprocess.run([sys.executable] + cmd)


menu()


