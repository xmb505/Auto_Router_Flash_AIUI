#!/bin/bash
# 刷入 OpenWRT 到备胎分区并启动
# 用法: ./flash_openwrt.sh

set -e

IP="${IP:-192.168.31.1}"
PASS="${PASS:-}"
DIR="files/xiaobai"
FW="$DIR/libwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi"

if [ ! -f "$FW" ]; then
    echo "文件不存在: $FW"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"
if [ -n "$PASS" ]; then
    SSH_CMD="sshpass -p '$PASS' ssh $SSH_OPTS"
    SCP_CMD="sshpass -p '$PASS' scp -O $SSH_OPTS"
else
    SSH_CMD="ssh $SSH_OPTS"
    SCP_CMD="scp -O $SSH_OPTS"
fi

# 1. 上传固件
echo "=== 上传固件到 $IP ==="
eval $SCP_CMD "$FW" root@$IP:/tmp/firmware.ubi

# 2. MD5 校验
echo "=== MD5 校验 ==="
LOCAL_MD5=$(md5sum "$FW" | cut -d' ' -f1)
REMOTE_MD5=$(eval $SSH_CMD root@$IP 'md5sum /tmp/firmware.ubi' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配！"
    exit 1
fi

# 3. 判断当前启动分区，写入备胎
CURRENT_ROOTFS=$(eval $SSH_CMD root@$IP 'nvram get flag_boot_rootfs')
echo "=== 当前 flag_boot_rootfs=$CURRENT_ROOTFS ==="

if [ "$CURRENT_ROOTFS" = "0" ]; then
    TARGET="rootfs_1"
    NEW_FLAG=1
    echo "→ 写入 mtd13 (rootfs_1)，切到 flag_boot_rootfs=1"
else
    TARGET="rootfs"
    NEW_FLAG=0
    echo "→ 写入 mtd12 (rootfs)，切到 flag_boot_rootfs=0"
fi

# 4. 擦除 + 写入
echo "=== 刷入 $TARGET ==="
eval $SSH_CMD root@$IP \
    "mtd write /tmp/firmware.ubi $TARGET && sync && echo '刷入完成'"

# 5. 切换启动标志
echo "=== 设置启动标志 ==="
eval $SSH_CMD root@$IP \
    "nvram set flag_boot_rootfs=$NEW_FLAG && \
     nvram set flag_last_success=$NEW_FLAG && \
     nvram commit && \
     echo 'nvram 已更新'"

# 6. 重启
echo "=== 重启进入 OpenWRT ==="
eval $SSH_CMD root@$IP 'reboot'
