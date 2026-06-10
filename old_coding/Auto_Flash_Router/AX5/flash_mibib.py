#!/usr/bin/env python3
"""通过 SSH 刷入大分区 MIBIB"""

import sys
import json
import argparse
import paramiko


def ssh_run(host, user, pwd, cmd, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd,
                   allow_agent=False, look_for_keys=False, timeout=15)
    _, stdout, stderr = client.exec_command(cmd, timeout=60)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    client.close()
    return exit_code, out, err


def scp_put(host, user, pwd, local, remote, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd,
                   allow_agent=False, look_for_keys=False, timeout=15)
    sftp = client.open_sftp()
    sftp.put(local, remote)
    sftp.close()
    client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='刷入大分区 MIBIB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '步骤:\n'
            '  1. SSH 上传 xiaomi-rm1800-mibib.bin 到路由器 /tmp\n'
            '  2. 备份当前 MIBIB 到 /tmp/mibib_backup.bin\n'
            '  3. 写入新 MIBIB 到 mtd1\n'
            '  4. 重启路由器\n'
        ))
    parser.add_argument('--host', default='192.168.31.1', help='路由器 IP')
    parser.add_argument('--user', default='root', help='SSH 用户 (默认: root)')
    parser.add_argument('--pwd', required=True, help='SSH 密码')
    parser.add_argument('--port', type=int, default=22, help='SSH 端口')
    parser.add_argument('--mibib', default='files/tmp/xiaomi-rm1800-mibib.bin',
                        help='MIBIB 文件路径')
    args = parser.parse_args()

    remote_path = '/tmp/xiaomi-rm1800-mibib.bin'
    backup_path = '/tmp/mibib_backup.bin'

    print(json.dumps({"step": "1/4", "msg": f"上传 MIBIB 到 {args.host}:{remote_path}"}))
    scp_put(args.host, args.user, args.pwd, args.mibib, remote_path, args.port)

    print(json.dumps({"step": "2/4", "msg": "备份当前 MIBIB…"}))
    code, out, err = ssh_run(args.host, args.user, args.pwd,
                             f"dd if=/dev/mtd1 of={backup_path}", args.port)
    if code != 0:
        print(json.dumps({"error": f"备份失败: {err}"}))
        sys.exit(1)

    print(json.dumps({"step": "3/4", "msg": "刷入新 MIBIB…"}))
    code, out, err = ssh_run(args.host, args.user, args.pwd,
                             f"mtd write {remote_path} '0:MIBIB'", args.port)
    if code != 0:
        print(json.dumps({"error": f"刷写失败: {err}"}))
        sys.exit(1)

    print(json.dumps({"step": "4/4", "msg": "重启路由器…"}))
    code, out, err = ssh_run(args.host, args.user, args.pwd, "reboot", args.port)

    print(json.dumps({"status": "ok",
                       "msg": "MIBIB 刷入完成，路由器已重启",
                       "backup": backup_path}))
