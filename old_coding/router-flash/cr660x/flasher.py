#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CR660X 刷机模块

实现两阶段刷机流程：
- Stage 1: 官方系统 -> 刷入 BOOTLOADER + KERNEL (initramfs)
- Stage 2: OpenWRT Initramfs -> 升级到最终固件
"""

import re
import time
import hashlib
import requests
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from config import config
from utils import NetworkTool, ShellTool, CryptoTool, WaitTool


class CR660XFlasher:
    """CR660X 刷机类"""

    def __init__(self, logger=None):
        self.logger = logger
        self.cfg = config.cr660x
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        # 设备 ID（从路由器 MAC 获取）
        self.device_id = "04:7c:16:da:51:cd"
        self.router_ip = None
        self.router_mac = None

    def _log(self, msg: str):
        """日志输出"""
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def detect_router(self, detected_ip: Optional[str] = None) -> Optional[str]:
        """检测路由器 IP

        Args:
            detected_ip: 如果已由外部检测到，直接传入可避免二次检测
        """
        self._log("正在检测路由器 IP...")

        # 如果外部已检测到 IP，直接使用
        if detected_ip:
            self.router_ip = detected_ip
            self.router_mac = NetworkTool.get_mac(detected_ip)
            self._log(f"检测到路由器: {detected_ip} (MAC: {self.router_mac})")
            return detected_ip

        detect_ips = self.cfg.get('detect_ips',
            ['192.168.2.1', '192.168.10.1', '192.168.31.1'])

        for ip in detect_ips:
            if NetworkTool.ping(ip, count=2):
                self.router_ip = ip
                self.router_mac = NetworkTool.get_mac(ip)
                self._log(f"检测到路由器: {ip} (MAC: {self.router_mac})")
                return ip

        self._log("未检测到路由器")
        return None

    def _get_key_iv(self) -> Tuple[Optional[str], Optional[str]]:
        """从网页获取 key 和 iv"""
        try:
            response = self.session.get(f"http://{self.router_ip}/cgi-bin/luci/web", timeout=10)
            web_content = response.text

            key_match = re.search(r"key:\s*'([^']+)'", web_content)
            iv_match = re.search(r"iv:\s*'([^']+)'", web_content)

            key = key_match.group(1) if key_match else None
            iv = iv_match.group(1) if iv_match else None

            return key, iv
        except Exception as e:
            self._log(f"获取 key/iv 失败: {e}")
            return None, None

    def _calc_password(self, password: str, key: str, nonce: str) -> str:
        """计算 SHA1 密码
        firstHash = SHA1(password + key)
        oldPwd = SHA1(nonce + firstHash)
        """
        first_hash = CryptoTool.sha1(password + key)
        old_pwd = CryptoTool.sha1(nonce + first_hash)
        return old_pwd

    def login(self, password: str) -> Tuple[bool, Optional[str]]:
        """登录路由器获取 stok（移动/电信版）"""
        key, iv = self._get_key_iv()
        if not key or not iv:
            return False, None

        # 生成 nonce
        timestamp = int(time.time())
        random_num = timestamp % 10000
        nonce = f"0_{self.device_id}_{timestamp}_{random_num}"

        # 计算密码 oldPwd = SHA1(nonce + SHA1(password + key))
        password_hash = self._calc_password(password, key, nonce)

        try:
            # 发送登录请求 (form-urlencoded)
            login_url = f"http://{self.router_ip}/cgi-bin/luci/api/xqsystem/login"

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            data = f"username=admin&password={password_hash}&logtype=2&nonce={nonce}"

            response = self.session.post(login_url, data=data, headers=headers, timeout=10)
            result = response.json()

            if result.get('code') == 0:
                # stok 从 url 字段提取
                url = result.get('url', '')
                stok_match = re.search(r';stok=([^/]+)', url)
                if stok_match:
                    stok = stok_match.group(1)
                    self._log(f"登录成功, stok: {stok}")
                    return True, stok

                self._log("登录成功但未获取到 stok")
                return False, None

            self._log(f"登录失败: {result.get('msg')}")
            return False, None

        except Exception as e:
            self._log(f"登录请求失败: {e}")
            return False, None

    def login_unicom_initial(self) -> Tuple[bool, Optional[str]]:
        """联通版第一次登录（GET 请求，密码 "admin"）
        
        参考旧版 unicom_flash.sh 第 1-85 行：
        - 使用 GET 请求
        - 密码是固定的 "admin"
        - 从 token 字段提取 stok
        """
        try:
            # 生成 nonce（联通版 mac 为空）
            timestamp = int(time.time())
            random_num = timestamp % 10000
            nonce = f"0__{timestamp}_{random_num}"

            # 联通版使用固定的 secret_key
            secret_key = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
            password = "admin"  # 联通版默认初始密码

            # 计算密码：hash1 = SHA1(password + secret_key), hash2 = SHA1(nonce + hash1)
            hash1 = CryptoTool.sha1(password + secret_key)
            encrypted_password = CryptoTool.sha1(nonce + hash1)

            # 发送 GET 请求
            login_url = f"http://{self.router_ip}/cgi-bin/luci/api/xqsystem/login"

            params = {
                'username': 'admin',
                'logtype': '2',
                'nonce': nonce,
                'password': encrypted_password,
                'init': '1',
                'privacy': '1'
            }

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0'
            }

            response = self.session.get(login_url, params=params, headers=headers, timeout=10)
            result = response.json()

            # 联通版从 token 字段提取 stok
            stok = result.get('token')
            if stok:
                self._log(f"联通版初始登录成功, stok: {stok}")
                return True, stok

            self._log(f"联通版初始登录失败: {result}")
            return False, None

        except Exception as e:
            self._log(f"联通版初始登录请求失败: {e}")
            return False, None

    def unicom_set_wan(self, stok: str) -> bool:
        """联通版设置 WAN（第一次登录后必须执行）
        
        参考旧版 unicom_flash.sh 第 86-99 行：
        - 调用 /api/xqnetwork/set_wan_new
        - 设置 WAN 类型为 DHCP
        """
        try:
            # 生成 nonce
            timestamp = int(time.time())
            random_num = timestamp % 10000
            nonce = f"0__{timestamp}_{random_num}"

            # 计算密码
            secret_key = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
            password = "admin"
            hash1 = CryptoTool.sha1(password + secret_key)
            encrypted_password = CryptoTool.sha1(nonce + hash1)

            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/xqnetwork/set_wan_new"

            data = f"wanType=dhcp&autoset=0&nonce={nonce}&password={encrypted_password}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            response = self.session.post(url, data=data, headers=headers, timeout=10)
            result = response.json()

            if result.get('code') == 0:
                self._log("WAN 设置成功")
                return True

            self._log(f"WAN 设置失败: {result}")
            return False

        except Exception as e:
            self._log(f"设置 WAN 失败: {e}")
            return False

    def unicom_vas_switch(self, stok: str) -> bool:
        """联通版 VAS Switch（第一次登录后必须执行）
        
        参考旧版 unicom_flash.sh 第 101-114 行：
        - 调用 /api/misystem/vas_switch
        - 设置 auto_upgrade=1
        """
        try:
            # 生成 nonce
            timestamp = int(time.time())
            random_num = timestamp % 10000
            nonce = f"0__{timestamp}_{random_num}"

            # 计算密码
            secret_key = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
            password = "admin"
            hash1 = CryptoTool.sha1(password + secret_key)
            encrypted_password = CryptoTool.sha1(nonce + hash1)

            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/misystem/vas_switch"

            params = {
                'info': 'auto_upgrade=1',
                'nonce': nonce,
                'password': encrypted_password
            }

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0'
            }

            response = self.session.get(url, params=params, headers=headers, timeout=10)
            result = response.json()

            if result.get('code') == 0:
                self._log("VAS Switch 成功")
                return True

            self._log(f"VAS Switch 失败: {result}")
            return False

        except Exception as e:
            self._log(f"VAS Switch 失败: {e}")
            return False

    def unicom_set_router_password(self, stok: str, new_password: str = "11111111") -> bool:
        """联通版设置路由器密码
        
        参考旧版 unicom_flash.sh 第 116-129 行：
        - 调用 /api/misystem/set_router_normal
        - 设置路由器管理密码
        """
        try:
            # 从网页获取 key 和 iv
            key, iv = self._get_key_iv()
            if not key:
                self._log("无法获取 key，设置密码失败")
                return False

            # 生成 nonce
            timestamp = int(time.time())
            random_num = timestamp % 10000
            nonce = f"0_{self.device_id}_{timestamp}_{random_num}"

            # 计算密码（使用新密码）
            password_hash = self._calc_password(new_password, key, nonce)

            # 配置参数
            exploit_wifi = self.cfg.get('exploit_wifi', {})
            wifi_ssid = exploit_wifi.get('ssid', 'MICR6608')

            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/misystem/set_router_normal"

            data = (
                f"name={wifi_ssid}&locale=\u5BB6&ssid={wifi_ssid}"
                f"&password={new_password}&encryption=mixed-psk"
                f"&nonce={nonce}&newPwd={password_hash}&oldPwd={password_hash}"
                f"&txpwr=1&routerPwd={new_password}"
            )

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            response = self.session.post(url, data=data, headers=headers, timeout=10)
            result = response.json()

            if result.get('code') == 0:
                self._log("路由器密码设置成功")
                return True

            self._log(f"路由器密码设置失败: {result}")
            return False

        except Exception as e:
            self._log(f"设置路由器密码失败: {e}")
            return False

    def get_sn(self, stok: str) -> Optional[str]:
        """获取路由器 SN 序列号（联通版专用）
        
        参考旧版 unicom_flash.sh：从 /api/misystem/newstatus 获取 hardware.sn
        """
        try:
            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/misystem/newstatus"
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0'
            }

            response = self.session.get(url, headers=headers, timeout=10)
            result = response.json()

            sn = result.get('hardware', {}).get('sn')
            if sn:
                self._log(f"获取到 SN: {sn}")
                return sn

            self._log(f"未能获取 SN: {result}")
            return None

        except Exception as e:
            self._log(f"获取 SN 失败: {e}")
            return None

    def calc_unicom_root_password(self, sn: str) -> str:
        """根据 SN 计算联通版 root 密码
        
        参考旧版 unicom_flash.sh：
        - 如果 SN 包含 "/"，使用 others_salt
        - 否则使用 r1d_salt
        - root_password = MD5(SN + salt)[:8]
        """
        r1d_salt = "A2E371B0-B34B-48A5-8C40-A7133F3B5D88"
        others_salt = "d44fb0960aa0-a5e6-4a30-250f-6d2df50a"

        # 根据 SN 是否包含斜杠来选择盐值
        if "/" in sn:
            salt = others_salt
        else:
            salt = r1d_salt

        # 计算 root 密码：MD5(SN + salt)[:8]
        root_password = CryptoTool.md5(sn + salt)[:8]
        self._log(f"计算得到的 root 密码: {root_password}")
        return root_password

    def enable_ssh(self, stok: str) -> bool:
        """通过命令注入漏洞开启 SSH"""
        try:
            # 获取配置的 SSID 和密码（命令注入破解辅助 Wi-Fi）
            exploit_wifi = self.cfg.get('exploit_wifi', {})
            wifi_ssid = exploit_wifi.get('ssid', 'MICR6608')
            wifi_password = exploit_wifi.get('password', '12345678')

            # 调用 extendwifi_connect API (GET 方法，参数在 URL 中)
            # 注意：此操作需要路由器连接 WiFi 并建立网络通道，可能需要较长时间
            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/misystem/extendwifi_connect?ssid={wifi_ssid}&password={wifi_password}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0'
            }

            self._log("正在开启 SSH（等待路由器连接 WiFi）...")
            response = self.session.get(url, headers=headers, timeout=60)
            result = response.json()

            # 检查返回值：兼容 code==0 和 msg 中包含 "connect succces!"
            if result.get('code') == 0 or 'connect succces' in str(result.get('msg', '')):
                self._log("SSH 已开启")
                return True

            self._log(f"开启 SSH 失败: {result.get('msg')}")
            return False
        except Exception as e:
            self._log(f"开启 SSH 失败: {e}")
            return False

    def open_ssh_channel(self, stok: str) -> bool:
        """打开 SSH 通道"""
        try:
            # 调用 oneclick_get_remote_token API (GET 方法)
            # 注意：此操作需要建立网络通道并执行远程命令，可能需要较长时间
            url = f"http://{self.router_ip}/cgi-bin/luci/;stok={stok}/api/xqsystem/oneclick_get_remote_token?username=xxx&password=xxx&nonce=xxx"

            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0'
            }

            self._log("正在打开 SSH 通道...")
            response = self.session.get(url, headers=headers, timeout=60)
            result = response.json()

            if result.get('code') == 0 and 'nvram' in str(result):
                self._log("SSH 通道已打开")
                return True

            self._log(f"打开 SSH 通道失败: {result.get('msg')}")
            return False
        except Exception as e:
            self._log(f"打开 SSH 通道失败: {e}")
            return False

    def upload_files(self, password: str) -> bool:
        """上传文件到路由器"""
        try:
            # 获取固件路径
            bootloader_path = config.get_firmware_path('cr660x',
                self.cfg.get('bootloader', 'pb-boot.img'))
            initramfs_path = config.get_firmware_path('cr660x',
                self.cfg.get('initramfs', 'sharewifi_initramfs-kernel.bin'))

            # SCP 上传 bootloader
            self._log("正在上传 Bootloader...")
            success = ShellTool.scp_file(
                bootloader_path,
                self.router_ip,
                'root',
                password,
                '/tmp/pb-boot.img'
            )
            if not success:
                self._log("❌ Bootloader 上传失败")
                return False
            self._log("✅ Bootloader 上传成功")

            # SCP 上传 initramfs
            self._log("正在上传 Initramfs...")
            success = ShellTool.scp_file(
                initramfs_path,
                self.router_ip,
                'root',
                password,
                '/tmp/sharewifi_initramfs-kernel.bin'
            )
            if not success:
                self._log("❌ Initramfs 上传失败")
                return False
            self._log("✅ Initramfs 上传成功")

            return True

        except Exception as e:
            self._log(f"上传文件失败: {e}")
            return False

    def flash_bootloader(self, password: str) -> bool:
        """刷入 Bootloader"""
        try:
            cmd = 'mtd write /tmp/pb-boot.img Bootloader'
            success, _ = ShellTool.ssh_cmd(
                self.router_ip,
                'root',
                password,
                cmd
            )
            return success
        except Exception as e:
            self._log(f"刷入 Bootloader 失败: {e}")
            return False

    def flash_initramfs(self, password: str) -> bool:
        """刷入 Initramfs 并重启"""
        try:
            cmd = 'sysupgrade --force /tmp/sharewifi_initramfs-kernel.bin'
            self._log("执行 sysupgrade（路由器将重启）...")
            success, output = ShellTool.ssh_cmd(
                self.router_ip,
                'root',
                password,
                cmd,
                timeout=30  # sysupgrade 可能需要一些时间
            )
            
            # sysupgrade 会导致 SSH 断开，这是正常行为
            # 只要命令开始执行（即使返回非零）也视为成功
            self._log("sysupgrade 已执行，路由器正在重启")
            return True
        except Exception as e:
            self._log(f"刷入 Initramfs 异常: {e}")
            # 即使是异常，也可能是因为路由器重启导致 SSH 断开
            # 检查输出中是否有 sysupgrade 相关信息
            return True  # 视为成功

    def stage3_upload_kernel(self) -> bool:
        """执行 Stage 3: Uboot HTTP 上传 Kernel 固件

        适用于路由器已处于 uboot 状态（192.168.1.1）的场景。
        通过 HTTP POST /upload.cgi 上传 kernel 文件，完成后自动重启进入 initramfs。
        完全复用 JGC stage3 的 HTTP 上传机制（uboot 硬件相同）。
        """
        self._log("=" * 40)
        self._log("Stage 3: Uboot -> Kernel (HTTP 上传)")
        self._log("=" * 40)

        uboot_ip = self.cfg.get('uboot_ip', '192.168.1.1')
        ping_interval = config.global_settings.get('ping_interval', 1)

        # 1. 等待 uboot 上线
        self._log(f"正在等待 {uboot_ip} 上线...")

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed}/{max_wait} 秒...")

        if not WaitTool.wait_for_ip(uboot_ip, max_wait=120, interval=ping_interval, callback=wait_callback):
            self._log("等待超时")
            return False

        self._log("UBoot 上线!")
        self.router_ip = uboot_ip
        self.router_mac = NetworkTool.get_mac(uboot_ip)

        # 2. 上传 kernel 固件（手动构造 multipart，与 JGC stage3 一致）
        self._log("正在上传 Kernel 固件...")
        firmware_path = config.get_firmware_path('cr660x',
            self.cfg.get('uboot_kernel', 'sharewifi_initramfs-kernel.bin'))

        if not firmware_path or not Path(firmware_path).exists():
            self._log(f"固件文件不存在: {firmware_path}")
            return False

        firmware_name = Path(firmware_path).name

        boundary = '----WebKitFormBoundarybqaq1PRB1QT3aVhC'
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}'
        }

        with open(firmware_path, 'rb') as f:
            firmware_data = f.read()

        post_data = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="firmware"; filename="{firmware_name}"\r\n'
            f'Content-Type: application/octet-stream\r\n'
            f'\r\n'
        ).encode('utf-8') + firmware_data + (
            f'\r\n--{boundary}--\r\n'
        ).encode('utf-8')

        try:
            response = self.session.post(
                f"http://{uboot_ip}/upload.cgi",
                data=post_data,
                headers=headers,
                timeout=120
            )

            # 检查响应中是否包含成功标识
            if 'successfully uploaded' in response.text.lower() or 'upload' in response.text.lower():
                self._log("固件上传成功")
            else:
                self._log(f"固件上传响应: {response.text[:200]}")
                # uboot 响应可能不标准，尝试继续

        except requests.exceptions.RequestException as e:
            # 处理 BadStatusLine 异常（uboot httpd 响应可能不标准）
            error_str = str(e).lower()
            if 'successfully uploaded' in error_str or 'upload' in error_str:
                self._log("固件上传成功")
            else:
                self._log(f"固件上传异常: {e}")
                return False

        # 3. 等待刷入完成（60 次 × 2s = 约 2 分钟）
        self._log("正在等待刷入完成...")
        max_retries = 60
        retry_count = 0

        while retry_count < max_retries:
            try:
                response = self.session.get(
                    f"http://{uboot_ip}/status.html", timeout=5)

                status_text = response.text.strip()

                # 提取 "status":"..." 和 "progress":"..."
                status_match = re.search(r'"status":"([^"]+)"', status_text)
                progress_match = re.search(r'"progress":"([^"]+)"', status_text)

                if status_match and progress_match:
                    status = status_match.group(1)
                    progress = progress_match.group(1)

                    self._log(f"刷机状态: {status}, 进度: {progress}%")

                    # 完成条件：status == 'done' AND progress == '100'
                    if status.lower() == 'done' and progress == '100':
                        self._log("刷机完成，准备重启...")
                        break

            except requests.exceptions.RequestException as e:
                # 处理 BadStatusLine 异常
                error_str = str(e)
                if 'status:"done"' in error_str and 'progress:"100"' in error_str:
                    self._log("刷机完成，准备重启...")
                    break
                elif 'status:"' in error_str and 'progress:"' in error_str:
                    # 从错误信息中提取状态
                    status_match = re.search(r'status:"([^"]+)"', error_str)
                    progress_match = re.search(r'progress:"([^"]+)"', error_str)

                    if status_match and progress_match:
                        status = status_match.group(1)
                        progress = progress_match.group(1)

                        self._log(f"刷机状态: {status}, 进度: {progress}%")

                        if status.lower() == 'done' and progress == '100':
                            self._log("刷机完成，准备重启...")
                            break

            time.sleep(2)
            retry_count += 1

        if retry_count >= max_retries:
            self._log("检查状态超时")
            return False

        # 4. 重启路由器
        try:
            self.session.get(f"http://{uboot_ip}/reboot.cgi", timeout=5)
            self._log("刷机完成，重启中...")
        except requests.exceptions.RequestException:
            # uboot 的 httpd 可能不会返回标准响应
            self._log("重启命令已发送 (uboot httpd 可能不返回标准响应)")

        return True

    def stage1_execute(self, password: str) -> bool:
        """执行 Stage 1: 刷入 BOOTLOADER + KERNEL"""
        self._log("=" * 40)
        self._log("Stage 1: 官方系统 -> BOOTLOADER + KERNEL")
        self._log("=" * 40)

        # 1. 登录获取 stok
        success, stok = self.login(password)
        if not success:
            return False

        # 2. 开启 SSH
        if not self.enable_ssh(stok):
            return False

        # 3. 打开 SSH 通道
        if not self.open_ssh_channel(stok):
            return False

        # 等待 SSH 服务启动
        time.sleep(2)

        # 4. 上传文件
        if not self.upload_files(password):
            return False

        # 5. 刷入 Bootloader
        self._log("正在刷入 Bootloader...")
        if not self.flash_bootloader(password):
            self._log("❌ Bootloader 刷入失败")
            return False
        self._log("✅ Bootloader 刷入成功")

        # 6. 刷入 Initramfs
        self._log("正在刷入 Initramfs...")
        if not self.flash_initramfs(password):
            self._log("❌ Initramfs 刷入失败")
            return False
        self._log("✅ Initramfs 刷入成功")

        # 7. 等待重启
        self._log("✅ Stage 1 完成，正在等待路由器重启...")

        return True

    def stage1_execute_unicom(self) -> bool:
        """执行 Stage 1: 联通版刷机流程
        
        联通版完整流程（参考 unicom_flash.sh）：
        1. 第一次登录（GET 请求，密码 "admin"）→ 获取 stok
        2. 设置 WAN（set_wan_new）
        3. VAS Switch（vas_switch）
        4. 设置路由器密码（set_router_normal）→ 将密码设置为 "11111111"
        5. 第二次登录（POST 请求，密码 "11111111"）→ 获取新 stok
        6. 获取 SN → 计算 root 密码
        7. 开启 SSH → 打开 SSH 通道
        8. 上传文件并刷机
        
        参考旧版 unicom_flash.sh
        """
        self._log("=" * 40)
        self._log("Stage 1: 官方系统 -> BOOTLOADER + KERNEL (联通版)")
        self._log("=" * 40)

        # 1. 第一次登录（GET 请求，密码 "admin"）
        self._log("正在执行第一次登录（初始密码: admin）...")
        success, stok = self.login_unicom_initial()
        if not success:
            self._log("❌ 第一次登录失败（路由器可能不是联通版或已设置过密码）")
            self._log("提示：如果路由器已设置过密码，请使用移动/电信版刷机流程")
            return False

        # 2. 设置 WAN
        self._log("正在设置 WAN...")
        if not self.unicom_set_wan(stok):
            self._log("⚠️ WAN 设置失败，继续执行...")

        # 3. VAS Switch
        self._log("正在执行 VAS Switch...")
        if not self.unicom_vas_switch(stok):
            self._log("⚠️ VAS Switch 失败，继续执行...")

        # 4. 设置路由器密码
        self._log("正在设置路由器密码...")
        new_password = "11111111"
        if not self.unicom_set_router_password(stok, new_password):
            self._log("❌ 设置路由器密码失败")
            return False

        # 5. 第二次登录（POST 请求，使用新密码）
        self._log("正在执行第二次登录（新密码）...")
        success, stok = self.login(new_password)
        if not success:
            self._log("❌ 第二次登录失败")
            return False

        # 6. 获取 SN 信息
        self._log("正在获取路由器 SN...")
        sn = self.get_sn(stok)
        if not sn:
            self._log("❌ 获取 SN 失败")
            return False

        # 7. 根据 SN 计算 root 密码
        root_password = self.calc_unicom_root_password(sn)

        # 8. 开启 SSH（使用 extendwifi_connect）
        if not self.enable_ssh(stok):
            return False

        # 9. 打开 SSH 通道（使用 root 密码）
        if not self.open_ssh_channel(stok):
            return False

        # 等待 SSH 服务启动
        time.sleep(2)

        # 10. 上传文件（使用 root 密码）
        self._log("正在上传文件（使用 root 密码）...")
        if not self.upload_files(root_password):
            return False

        # 11. 刷入 Bootloader
        self._log("正在刷入 Bootloader...")
        if not self.flash_bootloader(root_password):
            self._log("❌ Bootloader 刷入失败")
            return False
        self._log("✅ Bootloader 刷入成功")

        # 12. 刷入 Initramfs
        self._log("正在刷入 Initramfs...")
        if not self.flash_initramfs(root_password):
            self._log("❌ Initramfs 刷入失败")
            return False
        self._log("✅ Initramfs 刷入成功")

        # 13. 等待重启
        self._log("✅ Stage 1 完成，正在等待路由器重启...")

        return True

        # 2. 获取 SN 信息
        self._log("正在获取路由器 SN...")
        sn = self.get_sn(stok)
        if not sn:
            self._log("❌ 获取 SN 失败")
            return False

        # 3. 根据 SN 计算 root 密码
        root_password = self.calc_unicom_root_password(sn)

        # 4. 开启 SSH（使用 extendwifi_connect）
        if not self.enable_ssh(stok):
            return False

        # 5. 打开 SSH 通道（使用 root 密码）
        if not self.open_ssh_channel(stok):
            return False

        # 等待 SSH 服务启动
        time.sleep(2)

        # 6. 上传文件（使用 root 密码）
        self._log("正在上传文件（使用 root 密码）...")
        if not self.upload_files(root_password):
            return False

        # 7. 刷入 Bootloader
        self._log("正在刷入 Bootloader...")
        if not self.flash_bootloader(root_password):
            self._log("❌ Bootloader 刷入失败")
            return False
        self._log("✅ Bootloader 刷入成功")

        # 8. 刷入 Initramfs
        self._log("正在刷入 Initramfs...")
        if not self.flash_initramfs(root_password):
            self._log("❌ Initramfs 刷入失败")
            return False
        self._log("✅ Initramfs 刷入成功")

        # 9. 等待重启
        self._log("✅ Stage 1 完成，正在等待路由器重启...")

        return True

    def stage2_execute(self) -> bool:
        """执行 Stage 2: OpenWRT Initramfs -> 最终固件"""
        self._log("=" * 40)
        self._log("Stage 2: OpenWRT Initramfs -> 最终固件")
        self._log("=" * 40)

        wait_ip = self.cfg.get('stage2_wait_ip', '192.168.1.1')
        ssh_cfg = self.cfg.get('ssh', {})
        min_memory = self.cfg.get('min_memory', 248848)
        ping_interval = config.global_settings.get('ping_interval', 1)

        # 1. 等待 initramfs 启动（无限等待，原版脚本行为）
        self._log(f"正在等待 {wait_ip} 上线...")

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed} 秒...")

        if not WaitTool.wait_for_ip(wait_ip, max_wait=None, interval=ping_interval, callback=wait_callback):
            self._log("等待超时，路由器未上线")
            return False

        self._log(f"{wait_ip} 已上线")
        
        # 获取 MAC 地址（用于记录）
        self.router_ip = wait_ip
        self.router_mac = NetworkTool.get_mac(wait_ip)

        # 1.5 验证 SSH 是否可连接（区分 uboot 和 initramfs）
        # 注意：uboot 启动时会短暂 ping 通，然后掉线，最后 Linux 启动后又通
        # 所以需要持续尝试 SSH，直到成功或超时
        self._log("正在等待 initramfs 系统启动（SSH 可用）...")
        ssh_success = False
        max_wait = 120  # 最多等待 2 分钟
        elapsed = 0
        interval = 5
        
        while elapsed < max_wait:
            success, _ = ShellTool.ssh_cmd(
                wait_ip,
                'root',
                '',
                'echo OK',
                timeout=3
            )
            if success:
                ssh_success = True
                self._log("✅ SSH 连接成功，确认是 initramfs 系统")
                break
            
            # 每 15 秒显示一次进度
            if elapsed % 15 == 0:
                self._log(f"已等待 {elapsed}/{max_wait} 秒...")
            
            time.sleep(interval)
            elapsed += interval
        
        if not ssh_success:
            self._log("❌ 等待超时，initramfs 系统未启动")
            return False

        # 2. 检查内存
        self._log("正在检查内存...")
        try:
            cmd = f"ssh -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa root@{wait_ip} \"awk '/MemTotal/ {{print \\$2}}' /proc/meminfo\""
            returncode, stdout, _ = ShellTool.run(cmd.split(), timeout=10)

            if returncode == 0:
                mem_kb = int(stdout.strip())
                self._log(f"内存: {mem_kb} KB")

                if mem_kb < min_memory:
                    self._log(f"内存不足 {min_memory} KB")
                    return False
        except Exception as e:
            self._log(f"内存检查失败: {e}")
            return False

        # 3. 上传最终固件
        self._log("正在上传最终固件...")
        firmware_path = config.get_firmware_path('cr660x',
            self.cfg.get('sysupgrade', 'sharewifi_1.0.7.bin'))
        
        self._log(f"固件路径: {firmware_path}")

        # initramfs 中 root 用户无密码
        success = ShellTool.scp_file(
            firmware_path,
            wait_ip,
            'root',
            '',
            '/tmp/sharewifi_1.0.4.bin'  # 与原版一致
        )
        if not success:
            self._log("❌ 固件上传失败，请检查文件是否存在")
            return False
        
        self._log("✅ 固件上传成功")

        # 4. 执行升级
        self._log("正在执行系统升级...")
        success, output = ShellTool.ssh_cmd(
            wait_ip,
            'root',
            '',
            'sysupgrade /tmp/sharewifi_1.0.4.bin',
            timeout=30
        )
        
        # sysupgrade 会导致路由器重启和 SSH 断开，这是正常行为
        self._log("✅ sysupgrade 已执行，路由器正在重启")

        # 5. 等待 192.168.1.1 下线（确认路由器已重启，刷机完成）
        self._log("正在等待路由器重启（192.168.1.1 下线）...")

        max_wait = 60  # 最多等待 60 秒
        elapsed = 0
        interval = 2

        while elapsed < max_wait:
            if not NetworkTool.ping(wait_ip, timeout=1):
                self._log("✅ 路由器已重启，刷机完成！")
                self.router_mac = NetworkTool.get_mac(wait_ip)  # 重启前尝试获取 MAC
                return True

            if elapsed % 10 == 0:
                self._log(f"已等待 {elapsed}/{max_wait} 秒...")

            time.sleep(interval)
            elapsed += interval

        self._log(f"❌ 等待超时，路由器未重启 ({wait_ip})")
        return False

    def flash(self, password: str, carrier: str = 'mobile') -> Tuple[bool, Optional[str]]:
        """执行完整刷机流程"""
        self._log("开始 CR660X 刷机流程...")

        # Stage 1
        if not self.stage1_execute(password):
            return False, None

        # 等待重启后进入 Stage 2
        time.sleep(10)

        # Stage 2
        if not self.stage2_execute():
            return False, self.router_mac

        # 等待最终系统启动
        self._log("正在等待最终系统启动...")
        final_ip = self.cfg.get('final_ip', '10.11.12.1')

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed}/{max_wait} 秒...")

        if not WaitTool.wait_for_ip(final_ip, max_wait=120, callback=wait_callback):
            return True, self.router_mac  # MAC 已记录

        self._log("刷机完成!")
        return True, self.router_mac
