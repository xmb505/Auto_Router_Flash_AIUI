#!/usr/bin/env python3
"""
独立 TFTP 服务器 — 刷机固件分发服务

用途:
  uboot TFTP recovery 场景：路由器 uboot 启动后自动从本服务器拉取
  initramfs-recovery.itb / sysupgrade / factory.ubi 等固件。

来源:
  从旧版 src/project/ax3000t/6.tftp_recovery.py 抽离 + 改写。
  原脚本依赖系统 dnsmasq/atftpd，且步骤完成后退出。
  本版本为纯 Python 实现，常驻运行不退出。

特点:
  - 纯 Python socket 实现，零系统依赖（无需 dnsmasq/atftpd / sudo）
  - 只读模式 (RRQ)，不处理写入请求
  - 自动绑定同级 files/ 目录为 TFTP 根目录
  - 常驻运行，传完一个文件继续等下一个
  - --daemon 后台守护化
  - 信号处理优雅退出
  - 多客户端并发支持（selectors 事件循环 + per-client 状态机）

符合 doc/conventions/ 规范:
  - 00-coding-standards.md: snake_case 命名，常量 UPPER_CASE
  - 04-utility-contract.md: 工具脚本契约（--help-json, stdout JSON, stderr 日志）
  - 03-unix-philosophy.md: 做一件事、进度走 stderr、安静
"""

import argparse
import json
import os
import selectors
import signal
import socket
import struct
import sys
import time

# ==================== TFTP 协议常量 ====================
OP_RRQ = 1          # Read Request
OP_DATA = 3         # Data packet
OP_ACK = 4          # Acknowledgment
OP_ERROR = 5        # Error

ERR_FILE_NOT_FOUND = 1
ERR_ACCESS_VIOLATION = 2
ERR_ILLEGAL_OPERATION = 4
ERR_UNKNOWN_TID = 5

BLOCK_SIZE = 512
ACK_TIMEOUT = 5.0       # 等待 ACK 超时秒数
MAX_RETRIES = 5         # 最大重试次数
SESS_CLEANUP = 2.0      # 传输完成后保留秒数（收最后的 ACK）

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.join(SCRIPT_DIR, "files")


# ==================== 日志（stderr） ====================
DEBUG = False


def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG and level in ("INFO", "DEBUG"):
        return
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    print(f"{ts} [{level}] {msg}", file=sys.stderr, flush=True)


# ==================== TFTP 包构造 ====================
def make_data_pkt(block: int, data: bytes) -> bytes:
    """构造 DATA 包: opcode(2) + block(2) + payload(0-512)"""
    return struct.pack("!HH", OP_DATA, block & 0xFFFF) + data


def make_ack_pkt(block: int) -> bytes:
    """构造 ACK 包: opcode(2) + block(2)"""
    return struct.pack("!HH", OP_ACK, block & 0xFFFF)


def make_error_pkt(code: int, msg: str) -> bytes:
    """构造 ERROR 包: opcode(2) + errcode(2) + errmsg + \\0"""
    return struct.pack("!HH", OP_ERROR, code & 0xFFFF) + msg.encode() + b"\x00"


def parse_rrq(data: bytes):
    """解析 RRQ；成功返回 (filename, mode)，否则返回 None"""
    if len(data) < 4:
        return None
    opcode = struct.unpack("!H", data[:2])[0]
    if opcode != OP_RRQ:
        return None
    parts = data[2:].split(b"\x00")
    if len(parts) < 3:
        return None
    fname = parts[0].decode("ascii", errors="replace")
    mode = parts[1].decode("ascii", errors="replace").lower()
    return fname, mode


def parse_ack(data: bytes):
    """解析 ACK；返回 block number 或 None"""
    if len(data) < 4:
        return None
    opcode = struct.unpack("!H", data[:2])[0]
    if opcode != OP_ACK:
        return None
    block = struct.unpack("!H", data[2:4])[0]
    return block


# ==================== TFTP 会话状态机 ====================
class TftpSession:
    """单个客户端文件传输会话"""

    __slots__ = (
        "addr", "filename", "filepath", "_fp", "_block",
        "_last_pkt", "_last_time", "_retries", "_done",
    )

    def __init__(self, addr: tuple, filepath: str):
        self.addr = addr
        self.filename = os.path.basename(filepath)
        self.filepath = filepath
        self._fp = open(filepath, "rb")
        self._block = 1
        self._last_pkt = None    # 最近发送的 DATA 包 bytes
        self._last_time = 0.0    # 最近发送时间戳
        self._retries = 0
        self._done = False       # 标记为可清理

    def send_first_block(self, sock: socket.socket) -> None:
        """发送第一个 DATA 块"""
        data = self._fp.read(BLOCK_SIZE)
        pkt = make_data_pkt(self._block, data)
        sock.sendto(pkt, self.addr)
        self._last_pkt = pkt
        self._last_time = time.monotonic()
        log(f"SEND {self.addr}: block {self._block} ({len(data)} bytes)")

    def handle_ack(self, block: int, sock: socket.socket) -> bool:
        """收到 ACK；返回 True = 传输完成"""
        if block != self._block:
            # 重复 ACK（客户端重传）或乱序 — 忽略
            log(f"DUPACK {self.addr}: block {block} (expect {self._block})",
                level="DEBUG")
            return False

        # 上次 DATA < 512 bytes → 传输完成
        if len(self._last_pkt) < BLOCK_SIZE + 4:  # +4 for opcode+block
            self._done = True
            self._last_time = time.monotonic()
            log(f"DONE {self.addr}: {self.filename}")
            self._fp.close()
            return True

        # 发送下一块
        self._block += 1
        if self._block > 0xFFFF:
            self._block = 1
        self._retries = 0

        data = self._fp.read(BLOCK_SIZE)
        pkt = make_data_pkt(self._block, data)
        sock.sendto(pkt, self.addr)
        self._last_pkt = pkt
        self._last_time = time.monotonic()
        log(f"SEND {self.addr}: block {self._block} ({len(data)} bytes)")

        # 最后一块
        if len(data) < BLOCK_SIZE:
            self._done = True
            self._last_time = time.monotonic()
            log(f"DONE {self.addr}: {self.filename}")
            self._fp.close()
            return True
        return False

    def handle_timeout(self, sock: socket.socket) -> bool:
        """超时处理；返回 True = 放弃传输"""
        self._retries += 1
        if self._retries > MAX_RETRIES:
            log(f"TIMEOUT {self.addr}: 放弃 {self.filename} "
                f"(重试 {MAX_RETRIES} 次)")
            self._fp.close()
            return True
        # 重发最后的包
        sock.sendto(self._last_pkt, self.addr)
        self._last_time = time.monotonic()
        log(f"RETRY {self.addr}: block {self._block} "
            f"(#{self._retries})", level="DEBUG")
        return False

    @property
    def stale(self) -> bool:
        """传输完成后可清理"""
        return self._done and (time.monotonic() - self._last_time) > SESS_CLEANUP

    @property
    def timed_out(self) -> bool:
        """是否 ACK 超时"""
        return (not self._done
                and self._last_pkt is not None
                and (time.monotonic() - self._last_time) > ACK_TIMEOUT)


# ==================== 服务器主循环 ====================
def run_server(root: str, port: int, bind: str) -> None:
    """启动 TFTP 服务器主循环（selectors 事件驱动）"""
    # 验证根目录
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        log(f"根目录不存在: {root}", level="ERROR")
        sys.exit(1)
    os.chdir(root)
    log(f"TFTP 根目录: {root}")

    # 创建 UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind, port))
    except PermissionError:
        log(f"需要 root 权限绑定端口 {port}。", level="ERROR")
        log(f"试试: sudo {sys.argv[0]} --port 9999", level="ERROR")
        sys.exit(1)
    except OSError as e:
        log(f"绑定失败: {e}", level="ERROR")
        sys.exit(1)

    sock.setblocking(False)
    log(f"监听 {bind}:{port}")

    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ)

    sessions: dict = {}        # addr → TftpSession
    running = True

    # 信号处理
    def shutdown(signum, frame):
        nonlocal running
        log(f"收到信号 {signum}，正在关闭...")
        running = False
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while running:
        # 检查超时会话（每 1s 轮询一次）
        now = time.monotonic()
        for addr in list(sessions.keys()):
            sess = sessions[addr]
            if sess.stale:
                del sessions[addr]
                log(f"CLEANUP {addr}: {sess.filename}", level="DEBUG")
            elif sess.timed_out:
                abort = sess.handle_timeout(sock)
                if abort:
                    del sessions[addr]

        # select 等待 1s
        events = sel.select(timeout=1.0)
        if not events:
            continue

        for key, _ in events:
            data, addr = sock.recvfrom(1024)
            if addr[0] == bind:
                # 忽略自身发出的回复
                continue

            # === 已有会话：处理 ACK ===
            if addr in sessions:
                block = parse_ack(data)
                if block is not None:
                    done = sessions[addr].handle_ack(block, sock)
                    if done:
                        pass  # 等 stale 清理
                else:
                    log(f"UNEXPECTED {addr}: 非 ACK 包", level="DEBUG")
                continue

            # === 新会话：处理 RRQ ===
            rrq = parse_rrq(data)
            if rrq is None:
                err = make_error_pkt(ERR_ILLEGAL_OPERATION,
                                     "Illegal TFTP operation")
                sock.sendto(err, addr)
                log(f"REJECT {addr}: 不支持的请求操作", level="DEBUG")
                continue

            fname, mode = rrq
            if mode not in ("octet", "netascii"):
                err = make_error_pkt(ERR_ILLEGAL_OPERATION,
                                     f"Unsupported mode: {mode}")
                sock.sendto(err, addr)
                log(f"REJECT {addr}: mode={mode}", level="DEBUG")
                continue

            filepath = os.path.normpath(os.path.join(root, fname))
            # 安全检查：必须仍在根目录下
            if not filepath.startswith(root):
                err = make_error_pkt(ERR_ACCESS_VIOLATION,
                                     "Access violation")
                sock.sendto(err, addr)
                log(f"REJECT {addr}: 路径越界 {fname}", level="WARNING")
                continue

            if not os.path.isfile(filepath):
                err = make_error_pkt(ERR_FILE_NOT_FOUND,
                                     f"File not found: {fname}")
                sock.sendto(err, addr)
                log(f"NOTFOUND {addr}: {fname}")
                continue

            fsize = os.path.getsize(filepath)
            sess = TftpSession(addr, filepath)
            sessions[addr] = sess
            sess.send_first_block(sock)
            log(f"RRQ {addr}: {fname} ({fsize} bytes, mode={mode})")

    # 清理
    sel.unregister(sock)
    sock.close()
    for addr, sess in sessions.items():
        if not sess._done:
            log(f"ABORT {addr}: {sess.filename}", level="WARNING")
    log("服务器已关闭")


# ==================== 守护化 ====================
def daemonize() -> None:
    """fork 到后台，脱离终端"""
    pid = os.fork()
    if pid > 0:
        # 父进程退出
        sys.exit(0)
    # 子进程：新会话、脱离终端
    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    # 重定向 stdin/stdout/stderr
    sys.stdin.close()
    sys.stdout.close()
    sys.stderr.close()
    os.close(0)
    os.close(1)
    os.close(2)
    os.open("/dev/null", os.O_RDONLY)
    os.open("/dev/null", os.O_WRONLY)
    os.open("/dev/null", os.O_WRONLY)


# ==================== CLI ====================
def help_json() -> None:
    schema = {
        "script": "tftp_server",
        "description": "独立 TFTP 服务器 — 刷机固件分发服务",
        "args": [
            {"name": "--root", "type": "string",
             "default": str(DEFAULT_ROOT),
             "required": False,
             "description": "TFTP 根目录（默认 service/tftp/files/）"},
            {"name": "--port", "type": "int", "default": 69,
             "required": False,
             "description": "监听端口（需要 root 绑定 69）"},
            {"name": "--bind", "type": "string", "default": "0.0.0.0",
             "required": False,
             "description": "绑定地址"},
            {"name": "--daemon", "type": "flag", "default": False,
             "required": False,
             "description": "后台守护化"},
            {"name": "--debug", "type": "flag", "default": False,
             "required": False,
             "description": "打印详细日志到 stderr"},
        ],
        "examples": [
            f"sudo {sys.argv[0]} --debug",
            f"{sys.argv[0]} --port 9999 --debug",
            f"sudo {sys.argv[0]} --daemon",
            f"{sys.argv[0]} --root ../ax3000t/files --port 9999",
        ],
    }
    print(json.dumps(schema, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="独立 TFTP 服务器 — 刷机固件分发服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "原理:\n"
            "  纯 Python 实现的 TFTP 只读服务器。路由器 uboot 内置\n"
            "  TFTP client 在启动时拉取 initramfs-recovery.itb 等固件。\n"
            "\n"
            "用法:\n"
            "  # 前台运行（调试）:\n"
            "  sudo python3 tftp_server.py --debug\n"
            "\n"
            "  # 非 root（用 >1024 端口）:\n"
            "  python3 tftp_server.py --port 9999 --debug\n"
            "\n"
            "  # 后台服务:\n"
            "  sudo python3 tftp_server.py --daemon\n"
            "\n"
            "  # 用其他固件目录:\n"
            "  sudo python3 tftp_server.py --root ../ax3000t/files --debug\n"
            "\n"
            "配网:\n"
            "  服务器与路由器应在同网段（192.168.1.x）。\n"
            "  可另开终端手动配置:\n"
            "    sudo ip addr add 192.168.1.254/24 dev eth0\n"
        ),
    )
    p.add_argument("--root", default=str(DEFAULT_ROOT),
                   help=f"TFTP 根目录（默认: {DEFAULT_ROOT}）")
    p.add_argument("--port", type=int, default=69,
                   help="监听端口（默认: 69，需要 root）")
    p.add_argument("--bind", default="0.0.0.0",
                   help="绑定地址（默认: 0.0.0.0）")
    p.add_argument("--daemon", action="store_true",
                   help="后台守护化（脱离终端）")
    p.add_argument("--debug", action="store_true",
                   help="打印详细日志")
    return p.parse_args()


def main() -> int:
    global DEBUG

    if "--help-json" in sys.argv:
        help_json()
        return 0

    args = parse_args()
    DEBUG = args.debug

    if args.daemon:
        log("守护化到后台...")
        daemonize()

    try:
        run_server(args.root, args.port, args.bind)
    except KeyboardInterrupt:
        log("用户中断")
    return 0


if __name__ == "__main__":
    sys.exit(main())
