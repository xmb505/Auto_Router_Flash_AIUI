#!/usr/bin/env python3
"""
极简 TFTP 服务器 — 像 tftpd64 一样简单

用法:
    python3 tftpd.py <共享目录>
    python3 tftpd.py <共享目录> --port 69
    python3 tftpd.py <共享目录> --timeout 30

Uboot 端:
    tftp 0x46000000 firmware.bin
    # 或
    tftpboot 0x46000000 firmware.bin

传输成功后服务器自动退出。
"""

import socket
import sys
import os
import argparse

RRQ = b'\x00\x01'  # Read Request
DATA = b'\x00\x03'  # Data
ACK = b'\x00\x04'   # Acknowledge
ERROR = b'\x00\x05' # Error
BLK_SIZE = 512


def make_error(code: int, msg: str) -> bytes:
    err = ERROR + code.to_bytes(2, 'big') + msg.encode() + b'\x00'
    return err


def serve(share_dir: str, port: int = 69, exit_after_done: bool = True):
    share_dir = os.path.abspath(share_dir)
    if not os.path.isdir(share_dir):
        print(f"错误: 目录不存在 {share_dir}", file=sys.stderr)
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    print(f"TFTP 服务器启动: 端口 {port}, 共享目录 {share_dir}")
    print(f"等待客户端连接...")

    while True:
        data, addr = sock.recvfrom(4096)
        if len(data) < 6 or data[:2] != RRQ:
            continue

        # 解析 RRQ
        nul1 = data.find(b'\x00', 2)
        if nul1 == -1:
            continue
        filename = data[2:nul1].decode()
        mode = data[nul1+1:data.find(b'\x00', nul1+1)].decode().lower()

        # 安全处理：防止路径穿越
        safe_name = os.path.basename(filename)  # 只取文件名，去掉路径
        filepath = os.path.join(share_dir, safe_name)

        print(f"\n收到 RRQ: {filename} 模式={mode} 来自 {addr}")
        if mode not in ('octet', 'netascii'):
            err = make_error(4, "仅支持 octet/netascii 模式")
            sock.sendto(err, addr)
            continue

        print(f"  实际路径: {filepath}")

        if not os.path.isfile(filepath):
            print(f"  文件不存在!")
            err = make_error(1, f"文件 {safe_name} 不存在")
            sock.sendto(err, addr)
            if exit_after_done:
                print("客户端请求失败，退出")
                break
            continue

        filesize = os.path.getsize(filepath)
        print(f"  文件大小: {filesize} bytes")

        # 用新端口传输
        tftp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tftp_sock.bind(('0.0.0.0', 0))
        tftp_sock.settimeout(5)
        tftp_addr = (addr[0], addr[1])  # 客户端地址（传输用客户端源端口）

        print(f"  传输端口: {tftp_sock.getsockname()[1]}")
        print(f"  开始传输...")

        with open(filepath, 'rb') as f:
            block = 1
            last_block = False

            while not last_block:
                chunk = f.read(BLK_SIZE)
                if len(chunk) < BLK_SIZE:
                    last_block = True

                pkt = DATA + block.to_bytes(2, 'big') + chunk
                sent = 0
                # 最多重试 5 次
                for attempt in range(5):
                    try:
                        tftp_sock.sendto(pkt, tftp_addr)
                        # 空包是结束标记，客户端可能已关闭，超时视为正常
                        ack, _ = tftp_sock.recvfrom(4)
                        if ack == ACK + block.to_bytes(2, 'big'):
                            sent = len(chunk)
                            break
                    except socket.timeout:
                        if last_block and len(chunk) == 0:
                            sent = 0
                            break  # 空包超时 = 客户端已收完, 正常结束
                        print(f"  超时重试 block {block} (尝试 {attempt+1}/5)")
                        continue

                if sent == 0 and not (last_block and len(chunk) == 0):
                    print(f"  发送 block {block} 失败, 终止传输")
                    tftp_sock.close()
                    break

                print(f"  block {block}: {len(chunk)} bytes  {'[最后]' if last_block else ''}", end='\r')
                block += 1

        tftp_sock.close()
        print(f"\n  传输完成: {filesize} bytes, {block-1} blocks")

        if exit_after_done:
            print("传输成功，服务器退出")
            break

    sock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='极简 TFTP 服务器')
    parser.add_argument('directory', help='共享目录')
    parser.add_argument('--port', type=int, default=69, help='监听端口 (默认 69, 需 root)')
    parser.add_argument('--no-exit', action='store_true', help='传输完成后不退出，继续服务')
    args = parser.parse_args()

    if args.port < 1024 and os.geteuid() != 0:
        print("警告: 端口 < 1024 需要 root 权限", file=sys.stderr)
        print("请用 sudo 运行 或 指定 --port 1024+", file=sys.stderr)
        sys.exit(1)

    serve(args.directory, args.port, exit_after_done=not args.no_exit)
