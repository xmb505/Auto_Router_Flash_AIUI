#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具模块
"""

import os
import re
import subprocess
import time
import hashlib
import base64
from typing import Optional, Tuple
from pathlib import Path

# 尝试导入 scapy，如果可用则使用 ARP ping
try:
    from scapy.all import ARP, Ether, srp
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


class NetworkTool:
    """网络工具类"""

    @staticmethod
    def ping(host: str, count: int = 1, timeout: int = 1, use_arp: bool = False) -> bool:
        """检测主机是否在线（局域网 1s 超时足够）
        
        Args:
            host: 目标 IP 地址
            count: ping 次数
            timeout: 超时时间（秒）
            use_arp: 是否使用 ARP ping（需要 scapy），默认 False（使用系统 ping）
        """
        # 使用系统 ping
        try:
            result = subprocess.run(
                ['ping', '-c', str(count), '-W', str(timeout), host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout + 1
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return False

    @staticmethod
    def arp_ping(host: str, timeout: float = 1) -> bool:
        """通过 ARP 请求检测设备是否在线（不依赖系统缓存）
        
        Args:
            host: 目标 IP 地址
            timeout: 超时时间（秒），支持浮点数
        """
        if not SCAPY_AVAILABLE:
            return False
        
        try:
            arp = ARP(pdst=host)
            ether = Ether(dst="ff:ff:ff:ff:ff:ff")
            packet = ether/arp
            
            result = srp(packet, timeout=timeout, verbose=False, retry=0)[0]
            return len(result) > 0
        except Exception:
            return False

    @staticmethod
    def get_mac(ip: str) -> Optional[str]:
        """获取 IP 对应的 MAC 地址"""
        try:
            # 优先使用 ARP ping 获取 MAC
            if SCAPY_AVAILABLE:
                try:
                    arp = ARP(pdst=ip)
                    ether = Ether(dst="ff:ff:ff:ff:ff:ff")
                    packet = ether/arp
                    
                    result = srp(packet, timeout=1, verbose=False, retry=0)[0]
                    if len(result) > 0:
                        return result[0][1].hwsrc.lower()
                except Exception:
                    pass
            
            # 回退到系统 ARP 表
            subprocess.run(['ping', '-c', '1', '-W', '1', ip],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)

            result = subprocess.run(['ip', 'neigh', 'show', ip],
                                  capture_output=True, text=True)
            output = result.stdout.strip()

            if output:
                match = re.search(r'([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})', output)
                if match:
                    return match.group(1).lower()

            return None
        except subprocess.SubprocessError:
            return None


class ShellTool:
    """Shell 工具类"""

    @staticmethod
    def run(cmd: list, timeout: int = 30, check: bool = False) -> Tuple[int, str, str]:
        """执行命令"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'Command timeout'
        except subprocess.SubprocessError as e:
            return -1, '', str(e)

    @staticmethod
    def ssh_cmd(host: str, user: str, password: str, command: str,
                timeout: int = 30) -> Tuple[bool, str]:
        """执行 SSH 命令（password 为空时用免密登录）"""
        base = [
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-o', 'HostKeyAlgorithms=+ssh-rsa',
            '-o', 'PubkeyAcceptedKeyTypes=+ssh-rsa',
        ]
        if password:
            cmd = ['sshpass', '-p', password] + base + [f'{user}@{host}', command]
        else:
            cmd = base + [f'{user}@{host}', command]
        returncode, stdout, stderr = ShellTool.run(cmd, timeout)
        return returncode == 0, stdout + stderr

    @staticmethod
    def scp_file(local_file: str, host: str, user: str, password: str,
                 remote_path: str, timeout: int = 60) -> bool:
        """SCP 上传文件（password 为空时用免密）"""
        base = [
            'scp', '-O',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'HostKeyAlgorithms=+ssh-rsa',
            '-o', 'PubkeyAcceptedKeyTypes=+ssh-rsa',
            '-P', '22', local_file,
            f'{user}@{host}:{remote_path}'
        ]
        if password:
            cmd = ['sshpass', '-p', password] + base
        else:
            cmd = base
        returncode, stdout, stderr = ShellTool.run(cmd, timeout)
        return returncode == 0


class CryptoTool:
    """加密工具类"""

    @staticmethod
    def sha1(data: str) -> str:
        """计算 SHA1 哈希"""
        return hashlib.sha1(data.encode()).hexdigest()

    @staticmethod
    def md5(data: str) -> str:
        """计算 MD5 哈希"""
        return hashlib.md5(data.encode()).hexdigest()

    @staticmethod
    def base64_encode(data: str) -> str:
        """Base64 编码"""
        return base64.b64encode(data.encode()).decode()


class WaitTool:
    """等待工具类"""

    @staticmethod
    def wait_for_ip(ip: str, max_wait: int = 120,
                    interval: float = 5, callback=None) -> bool:
        """等待 IP 上线
        
        Args:
            ip: 等待的 IP 地址
            max_wait: 最大等待时间（秒），None 表示无限等待
            interval: 轮询间隔（秒），支持浮点数如 0.5
            callback: 回调函数 callback(elapsed, max_wait)
        """
        elapsed = 0
        while max_wait is None or elapsed < max_wait:
            if NetworkTool.ping(ip):
                return True
            if callback:
                callback(elapsed, max_wait if max_wait else '∞')
            time.sleep(interval)
            elapsed += interval
        return False

    @staticmethod
    def countdown(seconds: int, callback=None):
        """倒计时"""
        for i in range(seconds, 0, -1):
            if callback:
                callback(i)
            time.sleep(1)
