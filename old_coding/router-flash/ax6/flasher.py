#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AX6 刷机模块 — 全部调用现有 CLI 脚本"""

import json, socket, subprocess, sys, time
from pathlib import Path
from utils import NetworkTool, ShellTool, WaitTool


class AX6Flasher:
    SCRIPTS_DIR = Path(__file__).parent
    FIRMWARE_DIR = SCRIPTS_DIR / "firmware"
    DEFAULT_IP = "192.168.31.1"

    def __init__(self, logger=None):
        self.logger = logger
        self.router_ip = None
        self.router_mac = None
        self.stok = None
        self.ssh_password = None

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
            return {"error": f"超时"}
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
            self._log("_wait_ssh: router_ip 为空")
            return False
        self._log(f"等待 SSH {ip}:22...")
        for i in range(timeout // 2):
            try:
                s = socket.create_connection((ip, 22), timeout=2)
                s.close()
                self._log("SSH 就绪")
                return True
            except (OSError, socket.timeout) as e:
                if i % 5 == 0:
                    self._log(f"  SSH 未就绪 ({e})")
                time.sleep(2)
        self._log("SSH 超时")
        return False

    # ── Stage 1a: 初始化+降级（不开SSH） ──
    def stage1_init(self, pwd="12345678", ssid="Xiaomi_AX6", wifi_pwd="12345678"):
        """检测 → 初始化(如需) → 降级(如需) → 返回 stok"""
        self._log("--- Stage 1: 初始化 ---")
        if not self.router_ip:
            return None
        init = self._run("check_init.sh", self.router_ip)
        if init.get("init") == -1:
            return None
        if init.get("init") == 0:
            self._log("已初始化，直接登录...")
            r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
            if "error" in r:
                self._log(f"登录失败: {r.get('error','')}")
                return None
            self.stok = r.get("stok")
        else:
            r = self._run("auto_init.py", "--ip", self.router_ip, "--admin-pwd", pwd,
                          "--ssid", ssid, "--wifi-pwd", wifi_pwd)
            if "error" in r:
                return None
            r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
            if "error" in r:
                return None
            self.stok = r.get("stok")

        ver = self._run("check_version.sh", self.router_ip).get("stdout", "")
        self._log(f"版本: {ver}")
        if "1.0." not in ver:
            fw = self.FIRMWARE_DIR / "RA69_1.0.16.bin"
            if fw.exists():
                r = self._run("downgrade.py", "--stok", self.stok, "--fw", str(fw), timeout=180)
                if "error" in r:
                    return None
                for _ in range(30):
                    if not NetworkTool.ping(self.router_ip):
                        break
                    time.sleep(2)
                WaitTool.wait_for_ip(self.router_ip, max_wait=180, interval=5)
                self._log("降级完成，重新初始化...")
                # recovery=1 清空了配置，需要重新 auto_init
                r = self._run("auto_init.py", "--ip", self.router_ip, "--admin-pwd", pwd,
                              "--ssid", ssid, "--wifi-pwd", wifi_pwd)
                if "error" in r:
                    return None
                r = self._run("login_get_stok.py", "--ip", self.router_ip, "--pwd", pwd)
                if "error" in r:
                    return None
                self.stok = r.get("stok")
        return self.stok

    # ── Stage 1b: WiFi注入开SSH（需已有 stok） ──
    def stage1_ssh(self, stok=None):
        """WiFi注入开SSH，返回密码或 None"""
        self._log("--- Stage 1.5: 开SSH ---")
        if stok:
            self.stok = stok
        if not self.stok:
            return None
        r = self._run("enable_ssh.py", "--ip", self.router_ip, "--stok", self.stok, timeout=180)
        if "error" in r:
            return None
        if not self._wait_ssh():
            return None
        r = self._run("get_wifi_password.py", "--ip", self.router_ip, "--stok", self.stok)
        if "error" in r:
            return None
        self.ssh_password = r.get("password")
        self._log(f"SSH: root/{self.ssh_password}")
        return self.ssh_password

    # ── (兼容旧接口) 完整 Stage 1 ──
    def stage1_enable_ssh(self, pwd="12345678", ssid="Xiaomi_AX6", wifi_pwd="12345678"):
        if not self.stage1_init(pwd, ssid, wifi_pwd):
            return 'fail'
        if self.stage1_ssh():
            return 'ok'
        return 'fail'

    # ── Stage 2: 刷过渡 OpenWRT → mtd12 → 重启后 IP 变 192.168.1.1 ──
    def stage2_flash_transition(self):
        self._log("--- Stage 2 ---")
        import os
        env = {**os.environ, 'IP': self.router_ip or self.DEFAULT_IP}
        if self.ssh_password:
            env['PASS'] = self.ssh_password
        r = subprocess.run(
            ["bash", str(self.SCRIPTS_DIR / "flash_openwrt.sh")],
            capture_output=True, text=True, timeout=180, cwd=str(self.SCRIPTS_DIR), env=env,
        )
        for line in r.stdout.split('\n'):
            self._log(line)
        # reboot 断开 SSH 返回 255 正常
        ok = r.returncode in (0, 255)
        if ok:
            self._log("重启中... IP 将变为 192.168.1.1")
        return ok

    # ── Stage 3: 刷MIBIB+Uboot (过渡 OpenWRT, 192.168.1.1 免密) ──
    def stage3_flash_uboot(self):
        self._log("--- Stage 3 ---")
        env = {**__import__('os').environ, 'IP': '192.168.1.1'}
        r = subprocess.run(
            ["bash", str(self.SCRIPTS_DIR / "flash_uboot.sh")],
            capture_output=True, text=True, timeout=120, cwd=str(self.SCRIPTS_DIR), env=env,
        )
        for line in r.stdout.split('\n'):
            self._log(line)
        return r.returncode == 0

    # ── Stage 4: Uboot上传 ──
    def stage4_uboot_upload(self):
        self._log("--- Stage 4 ---")
        files = list(self.FIRMWARE_DIR.glob("*factory*.ubi"))
        if not files:
            return False
        try:
            import requests
            with open(str(files[0]), 'rb') as f:
                requests.post("http://192.168.1.1/", files={"firmware": f}, timeout=600)
            self._log("上传完成")
            return True
        except requests.exceptions.ConnectionError:
            self._log("上传完成（uboot非标准响应）")
            return True
        except Exception as e:
            self._log(f"失败: {e}")
            return False

    # ── Stage 5: Overlay ──
    def stage5_apply_overlay(self):
        self._log("--- Stage 5 ---")
        files = sorted(self.FIRMWARE_DIR.glob("overlay-*.tar.gz"))
        if not files:
            return False
        ip = self.router_ip or "192.168.1.1"
        ok = ShellTool.scp_file(str(files[-1]), ip, "root", "", "/tmp/overlay-new.tar.gz", timeout=60)
        if not ok:
            return False
        ok, _ = ShellTool.ssh_cmd(ip, "root", "",
            "cd /tmp && tar -xzf overlay-new.tar.gz && cp -a overlay/* /overlay/upper/ "
            "&& rm -rf overlay overlay-new.tar.gz && echo OK")
        if not ok:
            return False
        ShellTool.ssh_cmd(ip, "root", "", "reboot", timeout=5)
        return True

    # ── 全自动 ──
    def auto_flash(self, pwd="12345678"):
        if self.stage1_enable_ssh(pwd) != 'ok':
            return False
        if not self.stage2_flash_transition():
            return False
        WaitTool.wait_for_ip("192.168.1.1", max_wait=180, interval=5)
        if not self.stage3_flash_uboot():
            return False
        self._log("路由器重启中，按住 Reset 不放，蓝灯亮后松手...")
        self._log("按 Enter 继续 Stage 4...")
        input()
        if not self.stage4_uboot_upload():
            return False
        WaitTool.wait_for_ip("192.168.1.1", max_wait=180, interval=5)
        return self.stage5_apply_overlay()
