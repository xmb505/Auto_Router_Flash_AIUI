#!/bin/bash
# 上传 uboot → 刷入 mtd5 (FIP) → 重启
# 用法: ./flash_uboot.sh [uboot文件路径]

UBOOT="${1:-files/openwrt/immortalwrt-25.12.0-mediatek-filogic-xiaomi_mi-router-ax3000t-ubootmod-bl31-uboot.fip}"
IP="192.168.31.1"
PASS="root"

if [ ! -f "$UBOOT" ]; then
    echo "文件不存在: $UBOOT"
    exit 1
fi

set -e

echo "=== 上传 uboot 到路由器 ==="
sshpass -p "$PASS" scp -O -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa "$UBOOT" root@$IP:/tmp/uboot.fip

echo "=== 检查 MD5 ==="
LOCAL_MD5=$(md5sum "$UBOOT" | cut -d' ' -f1)
REMOTE_MD5=$(sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP 'md5sum /tmp/uboot.fip' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配，终止！"
    exit 1
fi

echo "=== 刷入 mtd5 (FIP) ==="
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP \
    'mtd write /tmp/uboot.fip /dev/mtd5 && sync && echo "刷入完成"'

echo "=== 重启路由器 ==="
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP 'reboot'

echo "重启指令已发送，路由器即将重启进入新 uboot"
