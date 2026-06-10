#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AX3000T 刷机模块

封装 AX3000T 目录下的 CLI 脚本，为 TUI 提供简洁接口。

正确流程：
  Stage 1: 初始化检测 + 版本检测 + 开SSH
  Stage 2: 刷入自定义 Uboot → 重启
  Stage 3: TFTP 启动 initramfs（uboot 启动失败自动回退 TFTP）
  Stage 4: initramfs 中 sysupgrade 刷入完整固件
  Stage 5: 刷入自定义 overlay 包
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from utils import NetworkTool, ShellTool, WaitTool


class AX3000TFlasher:
    """AX3000T 刷机类"""

    SCRIPTS_DIR = Path(__file__).parent
    FIRMWARE_DIR = SCRIPTS_DIR / "firmware"
    DEFAULT_IP = "192.168.31.1"
    UBOOT_IP = "192.168.1.1"

    def __init__(self, logger=None):
        self.logger = logger
        self.router_ip = None
        self.router_mac = None
        self.stok = None
        self._tftp_proc = None

    def _log(self, msg: str):
        if self.logger:
            self.logger(msg)

    # ============================================================
    # 脚本运行器
    # ============================================================

    def _run_python(self, script: str, *args, timeout=60) -> dict:
        sp = self.SCRIPTS_DIR / script
        if not sp.exists():
            return {"error": f"脚本不存在: {sp}"}
        try:
            r = subprocess.run(
                [sys.executable, str(sp)] + list(args),
                capture_output=True, text=True, timeout=timeout,
                cwd=str(self.SCRIPTS_DIR),
            )
            for line in r.stderr.strip().split('\n'):
                if line.strip():
                    self._log(line)
            if r.returncode != 0:
                try:
                    return json.loads(r.stdout)
                except Exception:
                    return {"error": r.stderr.strip() or f"退出码 {r.returncode}"}
            return json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            return {"error": f"超时 ({timeout}s)"}
        except json.JSONDecodeError as e:
            return {"error": f"JSON解析失败: {e}"}
        except Exception as e:
            return {"error": str(e)}

    def _run_bash(self, script: str, *args, timeout=120) -> dict:
        sp = self.SCRIPTS_DIR / script
        if not sp.exists():
            return {"error": f"脚本不存在: {sp}"}
        try:
            r = subprocess.run(
                ["bash", str(sp)] + list(args),
                capture_output=True, text=True, timeout=timeout,
                cwd=str(self.SCRIPTS_DIR),
            )
            out = r.stdout.strip()
            if out:
                try:
                    return json.loads(out)
                except Exception:
                    pass
            return {"code": r.returncode, "stdout": out, "stderr": r.stderr.strip()}
        except subprocess.TimeoutExpired:
            return {"error": f"超时 ({timeout}s)"}
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # 检测
    # ============================================================

    def detect_router(self, detected_ip: Optional[str] = None) -> bool:
        if detected_ip:
            self.router_ip = detected_ip
            self.router_mac = NetworkTool.get_mac(detected_ip)
            self._log(f"检测到路由器: {detected_ip}")
            return True
        for ip in [self.DEFAULT_IP, self.UBOOT_IP]:
            if NetworkTool.ping(ip):
                self.router_ip = ip
                self.router_mac = NetworkTool.get_mac(ip)
                self._log(f"检测到路由器: {ip}")
                return True
        self._log("未检测到路由器")
        return False

    def check_init(self) -> dict:
        return self._run_bash("check_init.sh", self.router_ip or self.DEFAULT_IP)

    def check_version(self) -> str:
        r = self._run_bash("check_version.sh", self.router_ip or self.DEFAULT_IP)
        return r.get("stdout", "unknown")

    # ============================================================
    # Stage 1: 检测 + 开SSH
    # ============================================================

    def login(self, pwd: str) -> bool:
        r = self._run_python("login_get_stok.py",
                             "--ip", self.router_ip or self.DEFAULT_IP,
                             "--pwd", pwd)
        if "error" in r:
            self._log(f"登录失败: {r['error']}")
            return False
        self.stok = r.get("stok")
        return True

    def auto_init(self, admin_pwd: str, ssid: str = None, wifi_pwd: str = None) -> bool:
        args = ["--ip", self.router_ip or self.DEFAULT_IP, "--admin-pwd", admin_pwd]
        if ssid:
            args += ["--ssid", ssid]
        if wifi_pwd:
            args += ["--wifi-pwd", wifi_pwd]
        r = self._run_python("auto_init.py", *args, timeout=60)
        if "error" in r:
            self._log(f"初始化失败: {r['error']}")
            return False
        self.stok = r.get("stok")
        return True

    def enable_ssh(self, pwd: str = None, wait=True) -> bool:
        args = ["--ip", self.router_ip or self.DEFAULT_IP]
        if self.stok:
            args += ["--stok", self.stok]
        elif pwd:
            args += ["--pwd", pwd]
        else:
            self._log("需要密码或 stok")
            return False
        if wait:
            args.append("--wait")
        r = self._run_python("enable_ssh.py", *args, timeout=120)
        if r.get("error") and "注入" in str(r.get("error")):
            self._log(f"注入失败: {r['error']}")
            return False

        # 自己等 SSH 端口
        self._log("等待 SSH 端口 22 就绪...")
        import socket
        ip = self.router_ip or self.DEFAULT_IP
        for _ in range(60):
            try:
                s = socket.create_connection((ip, 22), timeout=2)
                s.close()
                self._log("SSH已就绪 (root/root)")
                return True
            except (OSError, socket.timeout):
                time.sleep(2)
        self._log("SSH 端口未就绪")
        return False

    def _wait_ssh(self, timeout=60) -> bool:
        return WaitTool.wait_for_ip(self.router_ip or self.DEFAULT_IP,
                                    max_wait=timeout, interval=2)

    def stage1_enable_ssh(self, pwd: str, ssid: str = None, wifi_pwd: str = None) -> str:
        """
        完整 Stage 1：检测状态 → 初始化(如需) → 开SSH
        返回: 'ok' | 'need_reset' | 'fail'
        """
        self._log("--- Stage 1: 开启 SSH ---")
        if not self.router_ip:
            return 'fail'
        init = self.check_init()
        if init.get("init") == -1:
            self._log("路由器不可达")
            return 'fail'
        if init.get("init") == 1:
            # init=1: 需要出厂初始化 → auto_init
            self._log("路由器未初始化，执行出厂初始化...")
            if not self.auto_init(pwd, ssid, wifi_pwd):
                self._log("出厂初始化失败")
                return 'fail'
            # auto_init 改掉了密码，需要重新登录取新 stok
            self._log("重新登录获取新 stok...")
            if not self.login(pwd):
                self._log("重新登录失败")
                return 'fail'
        else:
            # init=0: 已初始化 → 让工人恢复出厂设置
            self._log("路由器已被初始化过，无法自动处理")
            self._log("请工人按住路由器 Reset 孔 5-10 秒恢复出厂设置")
            return 'need_reset'

        # 执行 SSH 注入
        if self.enable_ssh(wait=True):
            return 'ok'
        return 'fail'

    # ============================================================
    # Stage 2: 刷 Uboot
    # ============================================================

    def stage2_flash_uboot(self, uboot_file: str = None) -> bool:
        """SSH上传uboot → mtd write mtd5 → reboot"""
        self._log("--- Stage 2: 刷写 Uboot ---")
        if not uboot_file:
            files = list(self.FIRMWARE_DIR.glob("*uboot*.fip"))
            if not files:
                self._log("未找到 uboot 固件")
                return False
            uboot_file = str(files[0])
        self._log(f"刷入: {uboot_file}")
        r = self._run_bash("flash_uboot.sh", uboot_file, timeout=120)
        if r.get("error"):
            self._log(f"失败: {r['error']}")
            return False
        self._log("Uboot刷写完成，路由器重启中...")
        self._log("重启后uboot启动失败将自动TFTP获取固件")
        return True

    # ============================================================
    # Stage 3: TFTP 启动 initramfs
    # ============================================================

    def stage3_start_tftp(self, timeout: int = 0) -> bool:
        """启动 TFTP 服务器，等待 uboot 来获取 initramfs-recovery.itb
        timeout=0 表示无限等待。返回 True 表示传输完成。
        """
        self._log("--- Stage 3: TFTP 启动 initramfs ---")
        itb_files = list(self.FIRMWARE_DIR.glob("*initramfs-recovery*"))
        if not itb_files:
            self._log("未找到 initramfs-recovery.itb")
            return False
        self._log(f"共享: {itb_files[0].name}")

        self._tftp_proc = subprocess.Popen(
            [sys.executable, str(self.SCRIPTS_DIR / "tftpd.py"),
             str(self.FIRMWARE_DIR)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # 无限等待，直到 TFTP 传输完成（tftpd.py 传完自动退出）
        if timeout > 0:
            start = time.time()
            while time.time() - start < timeout:
                if self._tftp_proc.poll() is not None:
                    self._log("TFTP 传输完成")
                    return True
                time.sleep(1)
            self._tftp_proc.kill()
            self._log("TFTP 超时")
            return False
        else:
            # 无限等待
            self._tftp_proc.wait()
            self._log("TFTP 传输完成")
            return True

    def wait_initramfs(self, timeout: int = 0) -> bool:
        """等待 initramfs 系统启动 (IP: 192.168.1.1)
        timeout=0 表示无限等待。
        """
        self._log(f"等待 initramfs 启动{' (无限等待)' if timeout == 0 else f' (最长 {timeout}s)'}...")
        ok = WaitTool.wait_for_ip("192.168.1.1", max_wait=timeout if timeout > 0 else None, interval=5)
        if ok:
            self._log("initramfs 已就绪 (192.168.1.1)")
            self.router_ip = "192.168.1.1"
        return ok

    def wait_openwrt(self, ip: str = "192.168.1.1", timeout: int = 180) -> bool:
        """等待 OpenWRT 系统就绪（通过 HTTP 检测，区分 initramfs）"""
        self._log(f"等待 OpenWRT 系统就绪 ({ip})...")
        import urllib.request
        start = time.time()
        while True:
            if timeout > 0 and time.time() - start > timeout:
                self._log("等待 OpenWRT 超时")
                return False
            try:
                r = urllib.request.urlopen(f"http://{ip}/", timeout=2)
                if r.getcode() == 200:
                    self._log(f"OpenWRT 已就绪 ({ip})")
                    self.router_ip = ip
                    return True
            except Exception:
                pass
            time.sleep(3)

    def stop_tftp(self):
        if self._tftp_proc:
            try:
                self._tftp_proc.kill()
            except Exception:
                pass
            self._tftp_proc = None

    # ============================================================
    # Stage 4: sysupgrade 刷入完整固件
    # ============================================================

    def stage4_sysupgrade(self, firmware_file: str = None) -> bool:
        """在 initramfs 中 SSH sysupgrade -F 刷入完整固件"""
        self._log("--- Stage 4: sysupgrade 刷入完整固件 ---")
        if not firmware_file:
            files = [f for f in self.FIRMWARE_DIR.glob("*squashfs-sysupgrade*.itb")
                     if "custom" not in f.name]
            if not files:
                self._log("未找到 sysupgrade 固件")
                return False
            firmware_file = str(sorted(files)[-1])

        ip = self.router_ip or "192.168.1.1"
        self._log(f"上传固件: {firmware_file}")
        ok = ShellTool.scp_file(firmware_file, ip, "root", "",
                                "/tmp/firmware.itb", timeout=120)
        if not ok:
            self._log("SCP 上传失败")
            return False
        self._log("执行 sysupgrade -F (SSH将断开)...")
        ShellTool.ssh_cmd(ip, "root", "", "sysupgrade -F /tmp/firmware.itb", timeout=30)
        self._log("sysupgrade 指令已发送")
        return True

    # ============================================================
    # Stage 5: 刷入自定义 overlay
    # ============================================================

    def stage5_apply_overlay(self, overlay_file: str = None) -> bool:
        """上传并解压 overlay 包到 /overlay，自动重启"""
        self._log("--- Stage 5: 刷入自定义 overlay ---")
        if not overlay_file:
            files = sorted(self.FIRMWARE_DIR.glob("overlay-*.tar.gz"))
            if not files:
                self._log("未找到 overlay 包")
                return False
            overlay_file = str(files[-1])

        ip = self.router_ip or "192.168.1.1"
        self._log(f"overlay: {overlay_file}")
        ok = ShellTool.scp_file(overlay_file, ip, "root", "",
                                "/tmp/overlay.tar.gz", timeout=60)
        if not ok:
            self._log("上传 overlay 失败")
            return False
        ok, out = ShellTool.ssh_cmd(ip, "root", "",
                                     "cd /overlay && tar -xzf /tmp/overlay.tar.gz "
                                     "&& echo OVERLAY_OK")
        if not ok:
            self._log("解压 overlay 失败")
            return False
        self._log("overlay 刷入完成，重启中...")
        ShellTool.ssh_cmd(ip, "root", "", "reboot", timeout=10)
        self._log("重启指令已发送")
        return True

    # ============================================================
    # 全自动
    # ============================================================

    def auto_flash(self, pwd: str, ssid: str = None, wifi_pwd: str = None) -> bool:
        """全自动刷机 Stage 1→5（各阶段间用户按提示操作硬件）"""
        result = self.stage1_enable_ssh(pwd, ssid, wifi_pwd)
        if result != 'ok':
            self._log(f"Stage 1 失败: {result}")
            return False
        if not self.stage2_flash_uboot():
            return False
        self._log("Stage 3: 启动 TFTP 服务器...")
        if not self.stage3_start_tftp(timeout=120):
            self._log("TFTP 服务器启动失败")
            return False
        self._log("等待 initramfs 启动...")
        if not self.wait_initramfs():
            return False
        if not self.stage4_sysupgrade():
            return False
        self._log("等待 sysupgrade 重启，OpenWRT 上线...")
        if not self.wait_openwrt(timeout=300):
            return False
        if not self.stage5_apply_overlay():
            return False
        self._log("\n✅ 全部完成！重启后即可使用")
        return True
