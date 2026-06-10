#!/bin/bash
# Stage 2: 刷过渡 OpenWRT (xiaomimtd12.bin) 到 mtd12 (rootfs)
# 官方参考: 刷机流程.md
#
# 关键:
#   - mtd12 是 rootfs 分区，用 mtd write (不是 ubiformat)
#   - xiaomimtd12.bin 是 raw mtd 镜像 (不是 UBI 格式)
#   - 统一设 flag_boot_rootfs=0，下次从 mtd12 启动
#   - 全量设置 nvram (boot_wait, uart_en, telnet_en, ssh_en 等)

IP="${IP:-192.168.31.1}"
PASS="${PASS:-}"
DIR="files/openwrt"
FW="$DIR/xiaomimtd12.bin"

if [ ! -f "$FW" ]; then
    echo "文件不存在: $FW"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"

_ssh() {
    if [ -n "$PASS" ]; then
        sshpass -p "$PASS" ssh $SSH_OPTS "$@"
    else
        ssh $SSH_OPTS "$@"
    fi
}

_scp() {
    if [ -n "$PASS" ]; then
        sshpass -p "$PASS" scp -O $SSH_OPTS "$@"
    else
        scp -O $SSH_OPTS "$@"
    fi
}

# 1. 设置 nvram
echo "=== 设置 nvram (boot_wait + ssh/telnet/uart) ==="
_ssh root@$IP "nvram set flag_last_success=0 \
    && nvram set flag_boot_rootfs=0 \
    && nvram set flag_boot_success=1 \
    && nvram set flag_try_sys1_failed=0 \
    && nvram set flag_try_sys2_failed=0 \
    && nvram set boot_wait=on \
    && nvram set uart_en=1 \
    && nvram set telnet_en=1 \
    && nvram set ssh_en=1 \
    && nvram commit \
    && echo 'nvram 已更新'"

# 2. 上传固件
echo "=== 上传 $FW → /tmp/xiaomimtd12.bin ==="
_scp "$FW" root@$IP:/tmp/xiaomimtd12.bin

# 3. MD5 校验
echo "=== MD5 校验 ==="
LOCAL_MD5=$(md5sum "$FW" | cut -d' ' -f1)
REMOTE_MD5=$(_ssh root@$IP 'md5sum /tmp/xiaomimtd12.bin 2>/dev/null || md5 /tmp/xiaomimtd12.bin 2>/dev/null' | cut -d' ' -f1)
echo "  本地: $LOCAL_MD5"
echo "  远程: $REMOTE_MD5"
if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "MD5 不匹配！"
    exit 1
fi

# 4. 刷写 mtd12 (rootfs)
echo "=== 刷写 /dev/mtd12 (rootfs) ==="
_ssh root@$IP "mtd erase /dev/mtd12 && mtd write /tmp/xiaomimtd12.bin /dev/mtd12 && sync && echo '刷入完成'"

# 5. 重启
echo "=== 重启进入过渡 OpenWRT ==="
_ssh root@$IP 'reboot'