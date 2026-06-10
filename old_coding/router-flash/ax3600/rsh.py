#!/usr/bin/env python3
"""AX3600 SSH/SCP 工具（基于 sshpass + 系统 ssh），兼容老旧加密算法"""

import subprocess
import sys
import json
import argparse
import shutil

SSH_OPTS = [
    "-o", "LogLevel=QUIET",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "GlobalKnownHostsFile=/dev/null",
    "-o", "HostKeyAlgorithms=ssh-rsa",
]


def check_sshpass():
    if not shutil.which("sshpass"):
        print("需要 sshpass，请先安装：", file=sys.stderr)
        print("  sudo apt install sshpass", file=sys.stderr)
        sys.exit(1)


def ssh_run(host, user, pwd, cmd, port=22):
    check_sshpass()
    r = subprocess.run(
        ["sshpass", "-p", pwd, "ssh", f"{user}@{host}", "-p", str(port),
         *SSH_OPTS, cmd],
        capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def scp_put(host, user, pwd, local, remote, port=22):
    check_sshpass()
    r = subprocess.run(
        ["sshpass", "-p", pwd, "scp", "-O", "-P", str(port),
         *SSH_OPTS, local, f"{user}@{host}:{remote}"],
        capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def scp_get(host, user, pwd, remote, local, port=22):
    check_sshpass()
    r = subprocess.run(
        ["sshpass", "-p", pwd, "scp", "-O", "-P", str(port),
         *SSH_OPTS, f"{user}@{host}:{remote}", local],
        capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='AX3600 SSH/SCP 工具（sshpass + 系统 ssh）',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='192.168.31.1')
    parser.add_argument('--user', default='root')
    parser.add_argument('--pwd', default='root')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('action', choices=['run', 'put', 'get'])
    parser.add_argument('arg1')
    parser.add_argument('arg2', nargs='?', default='')
    args = parser.parse_args()

    try:
        if args.action == 'run':
            code, out, err = ssh_run(args.host, args.user, args.pwd, args.arg1, args.port)
            if code == 0:
                print(out, end='')
            if err:
                print(err, end='', file=sys.stderr)
            sys.exit(code)

        elif args.action == 'put':
            if not args.arg2:
                print("put 需要远程路径", file=sys.stderr)
                sys.exit(1)
            code, out, err = scp_put(args.host, args.user, args.pwd, args.arg1, args.arg2, args.port)
            if err: print(err, end='', file=sys.stderr)
            if code == 0:
                print(json.dumps({"status": "ok", "action": "put",
                                  "local": args.arg1, "remote": args.arg2}))
            sys.exit(code)

        elif args.action == 'get':
            if not args.arg2:
                print("get 需要本地路径", file=sys.stderr)
                sys.exit(1)
            code, out, err = scp_get(args.host, args.user, args.pwd, args.arg1, args.arg2, args.port)
            if err: print(err, end='', file=sys.stderr)
            if code == 0:
                print(json.dumps({"status": "ok", "action": "get",
                                  "remote": args.arg1, "local": args.arg2}))
            sys.exit(code)

    except subprocess.TimeoutExpired:
        print("超时", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
