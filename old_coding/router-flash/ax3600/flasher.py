#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AX3600 刷机模块

Stage 1: 开启SSH (检测 → 初始化(如需) → 降级(如需) → 注入开SSH)
Stage 2: 刷过渡OpenWRT到备胎分区 → 重启
Stage 3: 过渡OpenWRT中刷MIBIB+Uboot → 断电重启
Stage 4: Uboot Web上传最终固件
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from utils import NetworkTool, ShellTool, WaitTool


class AX3600Flasher:
    """AX3600 刷机类"""

    SCRIPTS_DIR = Path(__file__).parent
    FIRMWARE_DIR = SCRIPTS_DIR / "firmware"
    DEFAULT_IP = "192.168.31.1"
    UBOOT_IP = "192.168.1.1"

    def __init__(self, logger=None):
        self.logger = logger
        self.router_ip = None
        self.router_mac = None
        self.stok = None

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

    def detect_router(self, detected_ip=None) -> bool:
        if detected_ip:
            self.router_ip = detected_ip
            self.router_mac = NetworkTool.get_mac(detected_ip)
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
    # Stage 1: 开启 SSH
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

    def downgrade(self, fw_file: str = None) -> bool:
        """降级到 1.0.17（如需）"""
        if not fw_file:
            candidates = list(self.FIRMWARE_DIR.glob("*1.0.17*"))
            if not candidates:
                self._log("未找到降级固件")
                return False
            fw_file = str(candidates[0])
        args = ["--ip", self.router_ip or self.DEFAULT_IP]
        if self.stok:
            args += ["--stok", self.stok]
        args += ["--fw", fw_file]
        self._log("降级固件到 1.0.17...")
        r = self._run_python("downgrade.py", *args, timeout=120)
        if "error" in r:
            self._log(f"降级失败: {r['error']}")
            return False
        self._log("降级成功，路由器重启中...")
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

        # 不管脚本报告什么，自己再等端口
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

    def stage1_enable_ssh(self, pwd: str, ssid: str = None, wifi_pwd: str = None) -> str:
        """
        Stage 1: 检测状态 → 初始化(如需) → 降级(如需) → 开SSH
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
            self._log("出厂状态，自动初始化...")
            if not self.auto_init(pwd, ssid, wifi_pwd):
                return 'fail'
            # auto_init 改密码了，重登录取新 stok
            if not self.login(pwd):
                return 'fail'
        else:
            self._log("已初始化，登录中...")
            if not self.login(pwd):
                return 'fail'

        # 检测版本，判断是否需要降级
        ver = self.check_version()
        self._log(f"固件版本: {ver}")
        if ver != "1.0.17" and "1.0." not in ver:
            self._log("版本非 1.0.x，降级到 1.0.17...")
            if not self.downgrade():
                self._log("降级失败")
                return 'fail'
            # 降级后路由器重启，等它上线
            self._log("等待路由器降级重启完成 (约 120s)...")
            ip = self.router_ip or self.DEFAULT_IP
            ok = WaitTool.wait_for_ip(ip, max_wait=180, interval=5)
            if not ok:
                self._log("路由器重启后未上线")
                return 'fail'
            self._log("路由器已重新上线，重新登录...")
            if not self.login(pwd):
                return 'fail'

        if self.enable_ssh(wait=True):
            return 'ok'
        return 'fail'

    # ============================================================
    # Stage 2: 刷过渡固件到备胎分区
    # ============================================================

    def stage2_flash_transition(self) -> bool:
        """SCP上传 R3600_mtd12.bin → 写入备胎分区 → nvram切换 → 重启"""
        self._log("--- Stage 2: 刷过渡 OpenWRT ---")
        fw = self.FIRMWARE_DIR / "R3600_mtd12.bin"
        if not fw.exists():
            self._log(f"未找到过渡固件: {fw}")
            return False

        ip = self.router_ip or "192.168.31.1"
        self._log(f"上传过渡固件到 {ip}...")
        ok = ShellTool.scp_file(str(fw), ip, "root", "root",
                                "/tmp/firmware.bin", timeout=120)
        if not ok:
            self._log("SCP 上传失败")
            return False
        self._log("上传成功")

        # 判断当前启动分区
        ok, out = ShellTool.ssh_cmd(ip, "root", "root",
                                     "nvram get flag_boot_rootfs", timeout=10)
        if not ok:
            self._log("获取 flag_boot_rootfs 失败")
            return False

        current = out.strip()
        if current == "0":
            target = "rootfs_1"
            new_flag = "1"
        else:
            target = "rootfs"
            new_flag = "0"
        self._log(f"当前 flag={current}，写入 {target}，新 flag={new_flag}")

        # mtd write
        ok, out = ShellTool.ssh_cmd(ip, "root", "root",
                                     f"mtd write /tmp/firmware.bin {target} && sync",
                                     timeout=120)
        if not ok:
            self._log("mtd write 失败")
            return False
        self._log("刷写完成")

        # 切启动标志
        ShellTool.ssh_cmd(ip, "root", "root",
                           f"nvram set flag_boot_rootfs={new_flag} && "
                           f"nvram set flag_last_success={new_flag} && nvram commit",
                           timeout=10)
        self._log("启动标志已切换，重启中...")
        ShellTool.ssh_cmd(ip, "root", "root", "reboot", timeout=5)
        return True

    def wait_openwrt_transition(self, timeout=180) -> bool:
        """等待过渡 OpenWRT 启动 (192.168.1.1)"""
        self._log("等待过渡 OpenWRT 启动...")
        ok = WaitTool.wait_for_ip("192.168.1.1", max_wait=timeout, interval=5)
        if ok:
            self._log("过渡 OpenWRT 已就绪 (192.168.1.1, 免密SSH)")
            self.router_ip = "192.168.1.1"
        return ok

    # ============================================================
    # Stage 3: 刷 MIBIB + Uboot
    # ============================================================

    def stage3_flash_uboot(self) -> bool:
        """在过渡 OpenWRT 中刷 MIBIB + Uboot，自动重启"""
        self._log("--- Stage 3: 刷 MIBIB + Uboot ---")

        mibib = self.FIRMWARE_DIR / "ax3600-mibib.bin"
        uboot = self.FIRMWARE_DIR / "ax3600-uboot.bin"
        if not mibib.exists() or not uboot.exists():
            self._log("MIBIB 或 Uboot 文件缺失")
            return False

        ip = "192.168.1.1"
        if not NetworkTool.ping(ip):
            self._log(f"过渡 OpenWRT 不在线 ({ip})")
            return False

        # 先设置 fw_setenv
        self._log("设置 fw_setenv...")
        ok, _ = ShellTool.ssh_cmd(ip, "root", "",
                                   "fw_setenv flag_last_success 0 && "
                                   "fw_setenv flag_boot_rootfs 0", timeout=10)
        if not ok:
            self._log("fw_setenv 失败，继续...")

        # 上传文件
        self._log("上传 MIBIB + Uboot...")
        for f, name in [(mibib, "mibib"), (uboot, "uboot")]:
            ok = ShellTool.scp_file(str(f), ip, "root", "",
                                    f"/tmp/ax3600-{name}.bin", timeout=60)
            if not ok:
                self._log(f"上传 {name} 失败")
                return False

        # 刷写
        self._log("刷入 MIBIB (mtd1)...")
        ShellTool.ssh_cmd(ip, "root", "",
                           "mtd erase /dev/mtd1 && "
                           "mtd write /tmp/ax3600-mibib.bin /dev/mtd1", timeout=30)
        self._log("刷入 Uboot (mtd7)...")
        ShellTool.ssh_cmd(ip, "root", "",
                           "mtd erase /dev/mtd7 && "
                           "mtd write /tmp/ax3600-uboot.bin /dev/mtd7 && sync",
                          timeout=30)
        self._log("刷写完成，自动重启...")
        ShellTool.ssh_cmd(ip, "root", "", "reboot", timeout=5)
        return True

    # ============================================================
    # Stage 4: Uboot Web 上传最终固件
    # ============================================================

    def stage4_uboot_upload(self, firmware_file: str = None) -> bool:
        """通过 uboot web UI 上传最终固件"""
        self._log("--- Stage 4: Uboot 上传最终固件 ---")

        if not firmware_file:
            files = list(self.FIRMWARE_DIR.glob("*factory*.ubi"))
            if not files:
                self._log("未找到 factory.ubi 固件")
                return False
            firmware_file = str(files[0])

        if not NetworkTool.ping("192.168.1.1"):
            self._log("Uboot 不在线 (192.168.1.1)")
            self._log("请按住 Reset 上电，蓝灯亮起后重试")
            return False

        self._log(f"上传: {firmware_file}")
        try:
            import requests
            with open(firmware_file, 'rb') as f:
                r = requests.post(
                    "http://192.168.1.1/",
                    files={"firmware": f},
                    timeout=600,
                )
            if r.status_code == 200:
                self._log("上传成功，uboot 正在刷写固件")
                self._log("请勿断电，等待路由器自动重启 (约 3-5 分钟)")
                return True
            else:
                self._log(f"HTTP {r.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            # uboot 的 HTTP 响应可能非标准
            self._log("上传完成（uboot 非标准响应，属正常）")
            return True
        except Exception as e:
            self._log(f"上传失败: {e}")
            return False

    # ============================================================
    # 全自动
    # ============================================================

    def auto_flash(self, pwd: str) -> bool:
        """全自动刷机 Stage 1→4"""
        if self.stage1_enable_ssh(pwd) != 'ok':
            return False
        if not self.stage2_flash_transition():
            return False
        self._log("等待过渡 OpenWRT 启动...")
        if not self.wait_openwrt_transition():
            return False
        if not self.stage3_flash_uboot():
            return False
        self._log("\n⚠️  路由器已重启，请手动进入 uboot 模式")
        self._log("  (断电 → 按住 Reset → 上电 → 蓝灯亮起)")
        input("   按 Enter 继续上传最终固件...")
        if not self.stage4_uboot_upload():
            return False
        self._log("\n✅ 全部完成！等待路由器自动重启进入 OpenWRT")
        return True
