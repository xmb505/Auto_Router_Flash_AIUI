#!/usr/bin/env python3
"""极简 TFTP 服务器 — 传输完自动退出"""

import socket, sys, os

RRQ = b'\x00\x01'
DATA = b'\x00\x03'
ACK = b'\x00\x04'
BLK = 512


def serve(share_dir: str, port: int = 69):
    share_dir = os.path.abspath(share_dir)
    if not os.path.isdir(share_dir):
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))

    while True:
        data, addr = sock.recvfrom(4096)
        if len(data) < 6 or data[:2] != RRQ:
            continue
        nul1 = data.find(b'\x00', 2)
        if nul1 == -1:
            continue
        filename = data[2:nul1].decode()
        filepath = os.path.join(share_dir, os.path.basename(filename))

        if not os.path.isfile(filepath):
            sock.sendto(ERROR + b'\x00\x01' + b'not found\x00', addr)
            continue

        tftp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tftp.bind(('0.0.0.0', 0))
        tftp.settimeout(5)

        with open(filepath, 'rb') as f:
            block = 1
            while True:
                chunk = f.read(BLK)
                last = len(chunk) < BLK
                for _ in range(5):
                    try:
                        tftp.sendto(DATA + block.to_bytes(2, 'big') + chunk, addr)
                        ack, _ = tftp.recvfrom(4)
                        if ack == ACK + block.to_bytes(2, 'big'):
                            break
                    except socket.timeout:
                        continue
                if last:
                    break
                block += 1

        tftp.close()
        break  # 传完退出

    sock.close()


ERROR = b'\x00\x05'

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: tftpd.py <共享目录>")
        sys.exit(1)
    serve(sys.argv[1])
