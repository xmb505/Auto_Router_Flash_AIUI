#!/bin/bash
# 通过 SSH 刷写固件到备胎分区
# 用法: ./flash_firmware.sh [固件文件]

FW="${1:-file/R3600_mtd12.bin}"
IP="192.168.31.1"
PASS="root"

if [ ! -f "$FW" ]; then
    echo "文件不存在: $FW"
    exit 1
fi

set -e

# 1. 上传固件
echo "=== 上传固件到 $IP ==="
sshpass -p "$PASS" scp -O -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa "$FW" root@$IP:/tmp/firmware.bin

# 2. MD5 校验
echo "=== MD5 校验 ==="
LOCAL_MD5=$(md5sum "$FW" | cut -d' ' -f1)
REMOTE_MD5=$(sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP 'md5sum /tmp/firmware.bin' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配，终止！"
    exit 1
fi

# 3. 判断当前启动分区，写入备胎
CURRENT_ROOTFS=$(sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP 'nvram get flag_boot_rootfs')
echo "=== 当前 flag_boot_rootfs=$CURRENT_ROOTFS ==="

if [ "$CURRENT_ROOTFS" = "0" ]; then
    TARGET="rootfs_1"   # mtd13
    NEW_FLAG=1
    echo "→ 写入 mtd13 (rootfs_1)，切到 flag_boot_rootfs=1"
else
    TARGET="rootfs"     # mtd12
    NEW_FLAG=0
    echo "→ 写入 mtd12 (rootfs)，切到 flag_boot_rootfs=0"
fi

# 4. 擦除 + 写入（直接用分区名，mtd 命令自动查 /proc/mtd）
echo "=== 刷入 $TARGET ==="
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP \
    "mtd write /tmp/firmware.bin $TARGET && sync && echo '刷入完成'"

# 5. 切换启动标志
echo "=== 设置启动标志 ==="
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP \
    "nvram set flag_boot_rootfs=$NEW_FLAG && \
     nvram set flag_last_success=$NEW_FLAG && \
     nvram commit && \
     echo 'nvram 已更新'"

# 6. 重启
echo "=== 重启路由器 ==="
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa root@$IP 'reboot'

echo "重启指令已发送，路由器即将从 $TARGET 启动"
