#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AX5 刷机模块 — Stage 1: 开SSH"""

import json, socket, subprocess, sys, time
from pathlib import Path
from utils import NetworkTool, ShellTool, WaitTool


class AX5Flasher:
    SCRIPTS_DIR = Path(__file__).parent
    FIRMWARE_DIR = SCRIPTS_DIR / "firmware"
    DEFAULT_IP = "192.168.31.1"

    def __init__(self, logger=None):
        self.logger = logger
        self.router_ip = None
        self.router_mac = None
        self.stok = None
        self.ssh_password = "password"  # AX5 固定密码
        self.local_ip = None  # chfs 服务器 IP（用于 unlock_ssh.sh）

    def _log(self, msg):
        if self.logger:
            self.logger(msg)

    def _run(self, script, *args, timeout=120):
        sp = self.SCRIPTS_DIR / script
        ext = '.sh' if script.endswith('.sh') else '.py'
        try:
            r = subprocess.run(
                ['bash' if ext == '.sh' else sys.executable, str(sp)] + list(args),
                capture_output=True, text=True, timeout=timeout, cwd=str(self.SCRIPTS_DIR),
            )
        except subprocess.TimeoutExpired:
            self._log(f"超时 ({timeout}s)")
            return {"error": "超时"}
        for line in r.stderr.strip().split('\n'):
            if line.strip():
                self._log(line)
        if r.stdout.strip():
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                pass
        return {"code": r.returncode, "stdout": r.stdout.strip()}

    def detect_router(self, ip=None):
        if ip:
            self.router_ip = ip
            self.router_mac = NetworkTool.get_mac(ip)
            return True
        for ip in [self.DEFAULT_IP, "192.168.1.1"]:
            if NetworkTool.ping(ip):
                self.router_ip = ip
                self.router_mac = NetworkTool.get_mac(ip)
                return True
        return False

    def check_init(self):
        return self._run("check_init.sh", self.router_ip or self.DEFAULT_IP)

    def _wait_ssh(self, timeout=60):
        ip = self.router_ip
        if not ip:
            return False
        self._log(f"等待 SSH {ip}:22...")
        for i in range(timeout // 2):
            try:
                s = socket.create_connection((ip, 22), timeout=2)
                s.close()
                self._log("SSH 就绪")
                return True
            except (OSError, socket.timeout):
                if i % 5 == 0:
                    self._log("  SSH 未就绪")
                time.sleep(2)
        self._log("SSH 超时")
        return False

    # ── Stage 1: 开SSH ──
    def stage1_enable_ssh(self, pwd="12345678"):
        """完整流程: check_init → auto_init(如需) → login → downgrade(如需) → enable_ssh"""
        self._log("--- Stage 1 ---")
        if not self.router_ip:
            return 'fail'

        # 检测状态
        init = self.check_init()
        if init.get("init") == -1:
            return 'fail'
        if init.get("init") == 0:
            self._log("已初始化，直接登录...")
            r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
            if "error" in r:
                return 'fail'
            self.stok = r.get("stok")
        else:
            self._log("出厂状态，执行初始化...")
            r = self._run("auto_init.py", "--ip", self.router_ip, "--admin-pwd", pwd)
            if "error" in r:
                return 'fail'
            # auto_init 改了密码，重新登录
            r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
            if "error" in r:
                return 'fail'
            self.stok = r.get("stok")

        # 检查版本，非 1.0.26 需降级
        ver = self._run("check_version.sh", self.router_ip).get("stdout", "")
        self._log(f"版本: {ver}")
        if ver != "1.0.26":
            fw = self.FIRMWARE_DIR / "RA67_1.0.26.bin"
            if fw.exists():
                self._log("降级到 1.0.26...")
                r = subprocess.run(
                    [sys.executable, str(self.SCRIPTS_DIR / "downgrade.py"),
                     "--stok", self.stok, "--fw", str(fw)],
                    timeout=180, cwd=str(self.SCRIPTS_DIR))
                if r.returncode != 0:
                    return 'fail'
                # 等待降级重启（recovery=1 清空配置，回出厂状态）
                for _ in range(30):
                    if not NetworkTool.ping(self.router_ip):
                        break
                    time.sleep(2)
                WaitTool.wait_for_ip(self.router_ip, max_wait=180, interval=5)
                self._log("降级完成，重新初始化...")
                r = self._run("auto_init.py", "--ip", self.router_ip, "--admin-pwd", pwd)
                if "error" in r:
                    return 'fail'
                r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
                if "error" in r:
                    return 'fail'
                self.stok = r.get("stok")

        # 开 SSH（需要 local_ip 提供 unlock_ssh.sh）
        if not self.local_ip:
            self._log("缺少 local_ip（chfs 服务器地址），无法注入")
            return 'fail'
        self._log("注入开SSH...")
        r = subprocess.run(
            [sys.executable, str(self.SCRIPTS_DIR / "enable_ssh.py"),
             "--ip", self.router_ip, "--stok", self.stok,
             "--local-ip", self.local_ip],
            timeout=30, cwd=str(self.SCRIPTS_DIR))
        if r.returncode != 0:
            return 'fail'
        self._log("等待 SSH 端口...")
        if not self._wait_ssh(timeout=120):
            return 'fail'
        self._log(f"SSH 就绪: root/{self.ssh_password}")
        return 'ok'

    # ── Stage 2: 刷过渡 OpenWRT ──
    def stage2_flash_transition(self):
        """SCP 上传 factory.ubi → ubiformat 备胎 → nvram → reboot"""
        self._log("--- Stage 2 ---")
        import os
        env = {k: v for k, v in os.environ.items() if v is not None}
        env['IP'] = self.router_ip or self.DEFAULT_IP
        env['PASS'] = self.ssh_password or "password"
        r = subprocess.run(
            ["bash", str(self.SCRIPTS_DIR / "flash_openwrt.sh")],
            timeout=180, cwd=str(self.SCRIPTS_DIR), env=env)
        if r.returncode not in (0, 255):
            return False
        self._log("重启中... IP 将变为 192.168.1.1")
        return True
