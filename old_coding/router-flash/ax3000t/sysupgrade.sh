#!/bin/bash
# SCP 上传 sysupgrade 固件 → ssh sysupgrade -F 强制刷写
# 用法: ./sysupgrade.sh <固件文件>
#        ./sysupgrade.sh --ip 192.168.1.1 --pwd root firmware.bin
#        ./sysupgrade.sh --pwd '' firmware.bin   # 免密登录

IP="192.168.1.1"
USER="root"
PASS=""  # 默认空密码 = 免密

while [ $# -gt 0 ]; do
    case "$1" in
        --ip) IP="$2"; shift 2 ;;
        --user) USER="$2"; shift 2 ;;
        --pwd) PASS="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 [--ip IP] [--user USER] [--pwd PASS] <固件文件>"
            echo "      --pwd '' = 免密登录 (默认)"
            exit 0 ;;
        *)
            if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                IP="$1"
            else
                FILE="$1"
            fi
            shift ;;
    esac
done

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    echo "错误: 固件文件不存在或未指定"
    exit 1
fi

BASE_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

if [ -n "$PASS" ]; then
    SCP_BASE=(sshpass -p "$PASS" scp -O "${BASE_OPTS[@]}")
    SSH_BASE=(sshpass -p "$PASS" ssh "${BASE_OPTS[@]}")
else
    SCP_BASE=(scp -O "${BASE_OPTS[@]}")
    SSH_BASE=(ssh "${BASE_OPTS[@]}")
fi

set -e

echo "=== 上传固件到 $IP ==="
"${SCP_BASE[@]}" "$FILE" "$USER@$IP:/tmp/firmware.bin"

echo "=== 检查 MD5 ==="
LOCAL_MD5=$(md5sum "$FILE" | cut -d' ' -f1)
REMOTE_MD5=$("${SSH_BASE[@]}" "$USER@$IP" 'md5sum /tmp/firmware.bin' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配，终止！"
    exit 1
fi

echo "=== 执行 sysupgrade -F ==="
"${SSH_BASE[@]}" "$USER@$IP" 'sysupgrade -F /tmp/firmware.bin'

echo "刷写指令已发送，路由器正在重启..."
