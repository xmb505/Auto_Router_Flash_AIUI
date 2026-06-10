#!/bin/bash
# Stage 2: 刷过渡 OpenWRT 到备胎分区
# 用法: IP=192.168.31.1 PASS=password ./flash_openwrt.sh

IP="${IP:-192.168.31.1}"
PASS="${PASS:-password}"
FW="files/factory.ubi"

if [ ! -f "$FW" ]; then
    echo "文件不存在: $FW"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"

_ssh() { sshpass -p "$PASS" ssh $SSH_OPTS "$@"; }
_scp() { sshpass -p "$PASS" scp -O $SSH_OPTS "$@"; }

# 1. 上传固件
echo "=== 上传固件到 $IP ==="
_scp "$FW" root@$IP:/tmp/factory.ubi

# 2. MD5 校验
echo "=== MD5 校验 ==="
LOCAL_MD5=$(md5sum "$FW" | cut -d' ' -f1)
REMOTE_MD5=$(_ssh root@$IP 'md5sum /tmp/factory.ubi' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配！"
    exit 1
fi

# 3. 判断当前启动分区
CURRENT=$(_ssh root@$IP 'nvram get flag_boot_rootfs')
echo "=== flag_boot_rootfs=$CURRENT ==="

if [ "$CURRENT" = "0" ]; then
    # 当前 rootfs(mtd18)，刷入备胎 rootfs_1(mtd19)
    TARGET=mtd19
    NEW_FLAG=1
    echo "→ 写入 mtd19 (rootfs_1)，切到 flag_boot_rootfs=1"
else
    # 当前 rootfs_1(mtd19)，刷入备胎 rootfs(mtd18)
    TARGET=mtd18
    NEW_FLAG=0
    echo "→ 写入 mtd18 (rootfs)，切到 flag_boot_rootfs=0"
fi

# 4. ubiformat 写入
echo "=== ubiformat /dev/$TARGET ==="
_ssh root@$IP "ubiformat /dev/$TARGET -y -f /tmp/factory.ubi && sync && echo '刷入完成'"

# 5. 设置 nvram
echo "=== 设置启动标志 ==="
_ssh root@$IP "nvram set flag_last_success=$NEW_FLAG && \
    nvram set flag_boot_rootfs=$NEW_FLAG && \
    nvram set flag_boot_success=1 && \
    nvram set flag_try_sys1_failed=0 && \
    nvram set flag_try_sys2_failed=0 && \
    nvram set boot_wait=on && \
    nvram set uart_en=1 && \
    nvram set telnet_en=1 && \
    nvram set ssh_en=1 && \
    nvram commit && echo 'nvram 已更新'"

# 6. 重启
echo "=== 重启进入 OpenWRT ==="
_ssh root@$IP 'reboot'