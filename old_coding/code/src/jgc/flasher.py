#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JGC 刷机模块

实现三阶段刷机流程：
- Stage 1: 官方固件 -> PDCN 系统
- Stage 2: PDCN 系统 -> Bootloader
- Stage 3: Bootloader -> 最终固件
"""

import re
import time
import base64
import requests
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

from config import config
from utils import NetworkTool, ShellTool, WaitTool


class JGCFlasher:
    """JGC 刷机类"""

    def __init__(self, logger=None, model: str = 'Q10'):
        self.logger = logger
        self.model = model  # 'Q10' or 'Qx'
        self.cfg = config.jgc
        self.session = requests.Session()
        self.session.verify = False  # 忽略 SSL 证书

        # 根据型号设置 IP
        if model == 'Q10':
            self.official_ip = self.cfg.get('detect_ips', {}).get('official', '192.168.10.1')
        else:
            self.official_ip = self.cfg.get('detect_ips', {}).get('official_qx', '192.168.2.1')

        self.pdcn_ip = self.cfg.get('detect_ips', {}).get('pdcn', '192.168.123.1')
        self.uboot_ip = self.cfg.get('detect_ips', {}).get('uboot', '192.168.1.1')
        self.final_ip = self.cfg.get('detect_ips', {}).get('final', '10.11.12.1')

        self.router_mac = None

    def _log(self, msg: str):
        """日志输出"""
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def detect_password(self) -> Optional[str]:
        """自动检测路由器密码

        旧版参考 (get_passwd.py):
        - 先访问首页，如果包含 cgi-bin/luci 则再次访问 /cgi-bin/luci
        - 从页面源码中提取 password 字段
        """
        self._log("正在检测路由器密码...")

        try:
            # 访问路由器首页
            response = self.session.get(f"http://{self.official_ip}", timeout=10)

            # 检查是否有重定向到 /cgi-bin/luci
            if response.status_code == 200 and "cgi-bin/luci" in response.text:
                response = self.session.get(f"http://{self.official_ip}/cgi-bin/luci", timeout=10)

            # 从页面源码中提取密码
            if response.status_code == 200:
                password_match = re.search(
                    r'document\.getElementById\("password"\)\.value="([^"]+)"',
                    response.text
                )

                if password_match:
                    password = password_match.group(1)
                    self._log(f"检测到密码: {password}")
                    return password

            return None
        except Exception as e:
            self._log(f"密码检测失败: {e}")
            return None

    def get_stok(self, password: str) -> Tuple[Optional[str], Optional[str]]:
        """登录获取 stok 和 sysauth

        旧版参考 (get_stok.py):
        - POST /cgi-bin/luci
        - data: username=base64("root"), pc_mac="00:0E:C6:34:2F:5A", password=base64(password)
        - 302 redirect: stok 从 Location header 提取, sysauth 从 Set-Cookie 提取
        """
        self._log("正在获取认证信息...")

        try:
            # Base64 编码用户名和密码（分别编码，非组合）
            username_encoded = base64.b64encode(b"root").decode('utf-8')
            password_encoded = base64.b64encode(password.encode('utf-8')).decode('utf-8')

            login_data = {
                'username': username_encoded,
                'pc_mac': '00:0E:C6:34:2F:5A',
                'password': password_encoded
            }

            response = self.session.post(
                f"http://{self.official_ip}/cgi-bin/luci",
                data=login_data,
                timeout=10,
                allow_redirects=False  # 不自动跟随重定向
            )

            # 检查 302 重定向
            if response.status_code == 302:
                # 从 Location 头部提取 stok
                location = response.headers.get('Location', '')
                stok_match = re.search(r'stok=([a-f0-9]+)', location)
                stok = stok_match.group(1) if stok_match else None

                # 从 Set-Cookie 头部提取 sysauth
                set_cookie = response.headers.get('Set-Cookie', '')
                sysauth_match = re.search(r'sysauth=([a-f0-9]+)', set_cookie)
                sysauth = sysauth_match.group(1) if sysauth_match else None

                if stok and sysauth:
                    self._log("获取认证信息成功")
                    return stok, sysauth

            self._log("获取认证信息失败，请检查密码是否正确")
            return None, None

        except Exception as e:
            self._log(f"登录失败: {e}")
            return None, None

    def upload_firmware(self, stok: str, sysauth: str) -> bool:
        """上传 PDCN 固件

        旧版参考 (put_firmware.py):
        - POST /cgi-bin/luci/;stok={stok}/api/JCGFirmware/upload_firmware
        - Headers: Referer, X-Requested-With, Origin 等
        - Cookies: sysauth
        - 然后 GET /cgi-bin/luci/;stok={stok}/api/JCGFirmware/check_firmware 验证
          support=True, size_correct=True, file_exists=True
        """
        self._log("正在上传 PDCN 固件...")

        try:
            firmware_path = config.get_firmware_path('jgc',
                self.cfg.get('pdcn_firmware', 'JCG-Q20-PDCN.bin'))

            if not firmware_path or not Path(firmware_path).exists():
                self._log(f"固件文件不存在: {firmware_path}")
                return False

            firmware_name = Path(firmware_path).name

            upload_url = f"http://{self.official_ip}/cgi-bin/luci/;stok={stok}/api/JCGFirmware/upload_firmware"

            headers = {
                'Referer': f'http://{self.official_ip}/cgi-bin/luci/;stok={stok}/rnt/advanceSetup/update',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': f'http://{self.official_ip}',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
            }

            cookies = {
                'sysauth': sysauth
            }

            with open(firmware_path, 'rb') as f:
                files = {
                    'image': (firmware_name, f, 'application/octet-stream')
                }

                response = self.session.post(
                    upload_url,
                    headers=headers,
                    cookies=cookies,
                    files=files,
                    timeout=60
                )

            if response.status_code != 200:
                self._log(f"固件上传失败，HTTP 状态码: {response.status_code}")
                return False

            result = response.json()
            if result.get("code") != 0:
                self._log(f"固件上传失败: {result}")
                return False

            # 验证固件
            self._log("正在验证固件...")
            if not self._check_firmware(stok, sysauth):
                self._log("固件验证失败")
                return False

            self._log("固件上传成功")
            return True

        except Exception as e:
            self._log(f"固件上传失败: {e}")
            return False

    def _check_firmware(self, stok: str, sysauth: str) -> bool:
        """检查固件是否验证成功

        旧版参考 (put_firmware.py -> check_firmware):
        - GET /cgi-bin/luci/;stok={stok}/api/JCGFirmware/check_firmware
        - 检查 support=True, size_correct=True, file_exists=True
        """
        try:
            url = f"http://{self.official_ip}/cgi-bin/luci/;stok={stok}/api/JCGFirmware/check_firmware"

            headers = {
                'Referer': f'http://{self.official_ip}/cgi-bin/luci/;stok={stok}/rnt/advanceSetup/update',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
            }

            cookies = {
                'sysauth': sysauth
            }

            response = self.session.get(url, headers=headers, cookies=cookies, timeout=20)

            if response.status_code != 200:
                return False

            result = response.json()

            if (result.get("support") is True and
                result.get("size_correct") is True and
                result.get("file_exists") is True):
                return True

            self._log(f"固件验证失败: {result}")
            return False

        except Exception as e:
            self._log(f"检查固件时出错: {e}")
            return False

    def confirm_upgrade(self, stok: str, sysauth: str) -> bool:
        """确认升级

        旧版参考 (confirm_upgrade.py):
        - GET /cgi-bin/luci/;stok={stok}/api/JCGFirmware/upgrade?keep_config=false
        - Headers: Referer, X-Requested-With 等
        - Cookies: sysauth
        """
        self._log("正在确认固件升级...")

        try:
            url = f"http://{self.official_ip}/cgi-bin/luci/;stok={stok}/api/JCGFirmware/upgrade?keep_config=false"

            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Referer': f'http://{self.official_ip}/cgi-bin/luci/;stok={stok}/rnt/advanceSetup/update',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
                'X-Requested-With': 'XMLHttpRequest'
            }

            cookies = {
                'sysauth': sysauth
            }

            response = self.session.get(url, headers=headers, cookies=cookies, timeout=20)

            if response.status_code != 200:
                self._log(f"确认升级失败，HTTP 状态码: {response.status_code}")
                return False

            result = response.json()

            if result.get("code") == 0:
                self._log("确认升级成功")
                return True

            self._log(f"确认升级失败: {result}")
            return False

        except Exception as e:
            self._log(f"确认升级失败: {e}")
            return False

    def stage1_execute(self) -> bool:
        """执行 Stage 1: 官方固件 -> PDCN"""
        self._log("=" * 40)
        self._log("Stage 1: 官方固件 -> PDCN")
        self._log("=" * 40)

        # 1. 检测密码
        password = self.detect_password()
        if not password:
            self._log("未能检测到密码，请手动输入")
            return False

        # 2. 获取认证信息
        stok, sysauth = self.get_stok(password)
        if not stok:
            return False

        # 3. 上传固件
        if not self.upload_firmware(stok, sysauth):
            return False

        # 4. 确认升级
        if not self.confirm_upgrade(stok, sysauth):
            return False

        # 5. 等待 PDCN 上线
        self._log(f"正在等待 {self.pdcn_ip} 上线...")

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed}/{max_wait} 秒...")

        if not WaitTool.wait_for_ip(self.pdcn_ip, max_wait=120, callback=wait_callback):
            self._log("等待超时")
            return False

        self.router_mac = NetworkTool.get_mac(self.pdcn_ip)
        self._log(f"PDCN 上线! MAC: {self.router_mac}")
        return True

    def stage1_wait_pdcn(self) -> bool:
        """等待 PDCN 系统上线（Stage 1 的最后一步）"""
        self._log(f"正在等待 {self.pdcn_ip} 上线...")

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed}/{max_wait} 秒...")

        if not WaitTool.wait_for_ip(self.pdcn_ip, max_wait=120, callback=wait_callback):
            self._log("等待超时")
            return False

        self.router_mac = NetworkTool.get_mac(self.pdcn_ip)
        self._log(f"PDCN 上线! MAC: {self.router_mac}")
        return True

    def stage2_execute(self) -> bool:
        """执行 Stage 2: PDCN -> Bootloader"""
        self._log("=" * 40)
        self._log("Stage 2: PDCN -> Bootloader")
        self._log("=" * 40)

        # 1. 检测 PDCN 在线
        if not NetworkTool.ping(self.pdcn_ip):
            self._log("PDCN 未上线")
            return False

        # 2. 下载 Bootloader（使用配置的 chfs IP）
        self._log("正在下载 Bootloader...")
        chfs_cfg = self.cfg.get('chfs', {})
        chfs_ip = chfs_cfg.get('ip', '192.168.123.5')
        chfs_port = chfs_cfg.get('port', 8080)

        download_url = f"http://{chfs_ip}:{chfs_port}/chfs/shared/pb-boot.img"

        try:
            cmd = f"wget -O /tmp/pb-boot.img {download_url}"
            success, _ = self._pdcn_exec(cmd)
            if not success:
                self._log("Bootloader 下载失败")
                return False
        except Exception as e:
            self._log(f"下载失败: {e}")
            return False

        # 3. 刷入 Bootloader
        self._log("正在刷入 Bootloader...")
        try:
            cmd = "mtd_write write /tmp/pb-boot.img Bootloader"
            success, _ = self._pdcn_exec(cmd)
            if not success:
                self._log("Bootloader 刷入失败")
                return False
        except Exception as e:
            self._log(f"刷入失败: {e}")
            return False

        # 4. 等待 3 秒（旧版 pdcn_flash_all.py 等待 3s）
        self._log("等待 3 秒...")
        time.sleep(3)

        # 5. 重启
        self._log("正在重启...")
        try:
            cmd = "reboot"
            self._pdcn_exec(cmd)
        except:
            pass

        return True

    def stage3_execute(self) -> bool:
        """执行 Stage 3: Bootloader -> 最终固件"""
        self._log("=" * 40)
        self._log("Stage 3: Bootloader -> 最终固件")
        self._log("=" * 40)

        # 1. 等待 uboot 上线
        self._log(f"正在等待 {self.uboot_ip} 上线...")

        def wait_callback(elapsed, max_wait):
            self._log(f"已等待 {elapsed}/{max_wait} 秒...")

        if not WaitTool.wait_for_ip(self.uboot_ip, max_wait=120, callback=wait_callback):
            self._log("等待超时")
            return False

        self._log("UBoot 上线!")

        # 2. 上传固件（手动构造 multipart，与旧版 uboot_flash.py 一致）
        self._log("正在上传最终固件...")
        firmware_path = config.get_firmware_path('jgc',
            self.cfg.get('final_firmware', 'sharewifi_1.0.7.bin'))

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
                f"http://{self.uboot_ip}/upload.cgi",
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
                # 立即释放内存
                del post_data
                import gc
                gc.collect()
                return False

        # 立即释放 post_data（上传已完成）
        del post_data
        # 强制垃圾回收，释放内存
        import gc
        gc.collect()

        # 3. 等待刷入完成（旧版 max_retries=60, sleep=2, 总等待约 2 分钟）
        self._log("正在等待刷入完成...")
        max_retries = 60
        retry_count = 0

        while retry_count < max_retries:
            try:
                response = self.session.get(
                    f"http://{self.uboot_ip}/status.html", timeout=5)

                status_text = response.text.strip()

                # 旧版正则：提取 "status":"..." 和 "progress":"..."
                status_match = re.search(r'"status":"([^"]+)"', status_text)
                progress_match = re.search(r'"progress":"([^"]+)"', status_text)

                if status_match and progress_match:
                    status = status_match.group(1)
                    progress = progress_match.group(1)

                    self._log(f"刷机状态: {status}, 进度: {progress}%")

                    # 旧版完成条件：status == 'done' AND progress == '100'
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

        # 4. 重启
        try:
            self.session.get(f"http://{self.uboot_ip}/reboot.cgi", timeout=5)
            self._log("刷机完成，重启中...")
        except requests.exceptions.RequestException:
            # uboot 的 httpd 可能不会返回标准响应
            self._log("重启命令已发送 (uboot httpd 可能不返回标准响应)")

        return True

    def _pdcn_exec(self, cmd: str) -> Tuple[bool, str]:
        """在 PDCN 系统执行命令

        旧版参考 (pdcn_put_bootloader.py, pdcn_flash_bootloader.py, pdcn_reboot.py):
        - POST /apply.cgi（注意：不是 /cgi-bin/apply.cgi）
        - POST data: action_mode= SystemCmd , current_page=console_response.asp,
          next_page=console_response.asp, SystemCmd=<cmd>
        - Headers: Authorization (Basic admin:admin), Referer, X-Requested-With, Origin 等
        - 等待 2s 后 GET /console_response.asp 获取命令执行结果
        """
        # Basic Auth (admin:admin) — 硬编码，与旧版一致
        AUTHORIZATION = "Basic YWRtaW46YWRtaW4="

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Authorization': AUTHORIZATION,
            'Referer': f'http://{self.pdcn_ip}/Advanced_Console_Content.asp',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': f'http://{self.pdcn_ip}',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
        }

        payload = {
            'action_mode': ' SystemCmd ',
            'current_page': 'console_response.asp',
            'next_page': 'console_response.asp',
            'SystemCmd': cmd
        }

        try:
            response = self.session.post(
                f"http://{self.pdcn_ip}/apply.cgi",
                data=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code != 200:
                return False, f"HTTP {response.status_code}: {response.text}"

            # 等待命令执行完成（旧版等待 2s）
            time.sleep(2)

            # 获取命令执行结果
            result_headers = {
                'Authorization': AUTHORIZATION,
                'Referer': f'http://{self.pdcn_ip}/Advanced_Console_Content.asp',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
            }

            result_response = self.session.get(
                f"http://{self.pdcn_ip}/console_response.asp",
                headers=result_headers,
                timeout=30
            )

            if result_response.status_code == 200:
                return True, result_response.text

            return False, f"获取结果失败 HTTP {result_response.status_code}"

        except Exception as e:
            return False, str(e)

    def flash(self, from_step: int = 1) -> Tuple[bool, Optional[str]]:
        """执行刷机流程"""
        self._log(f"开始 JGC 刷机流程 (从步骤 {from_step} 开始)...")

        # 检测路由器
        if not NetworkTool.ping(self.official_ip):
            self._log("路由器未上线")
            return False, None

        self.router_mac = NetworkTool.get_mac(self.official_ip)

        if from_step <= 1 and not self.stage1_execute():
            return False, self.router_mac

        if from_step <= 2:
            if not WaitTool.wait_for_ip(self.pdcn_ip, max_wait=30):
                return False, self.router_mac
            if not self.stage2_execute():
                return False, self.router_mac

            # 等待 uboot 上线
            if not WaitTool.wait_for_ip(self.uboot_ip, max_wait=60):
                return False, self.router_mac

        if from_step <= 3:
            if not self.stage3_execute():
                return False, self.router_mac

            # 等待最终系统
            self._log("正在等待最终系统启动...")
            if not WaitTool.wait_for_ip(self.final_ip, max_wait=120):
                return True, self.router_mac

        self._log("刷机完成!")
        return True, self.router_mac
