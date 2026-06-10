#!/bin/bash
# 刷入自定义 MIBIB (分区表) + Uboot
# 用法: ./flash_uboot.sh [--pwd 5GWiFi密码]

set -e

IP="${IP:-192.168.31.1}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"
DIR="files/openwrt"

# 密码处理
PASS=""
if [ "$1" = "--pwd" ]; then
    PASS="$2"
    SSH_CMD="sshpass -p '$PASS' ssh $SSH_OPTS"
    SCP_CMD="sshpass -p '$PASS' scp -O $SSH_OPTS"
else
    SSH_CMD="ssh $SSH_OPTS"
    SCP_CMD="scp -O $SSH_OPTS"
fi

echo "=== 上传 MIBIB + Uboot ==="
eval $SCP_CMD "$DIR/ax6-mibib-stock.bin" root@$IP:/tmp/
eval $SCP_CMD "$DIR/ax6-uboot-stock.bin" root@$IP:/tmp/

echo "=== MD5 校验 ==="
for f in ax6-mibib-stock.bin ax6-uboot-stock.bin; do
    LOCAL=$(md5sum "$DIR/$f" | cut -d' ' -f1)
    REMOTE=$(eval $SSH_CMD root@$IP "md5sum /tmp/$f" | cut -d' ' -f1)
    echo "  $f: local=$LOCAL remote=$REMOTE"
    [ "$LOCAL" = "$REMOTE" ] || { echo "MD5 不匹配"; exit 1; }
done

echo "=== 刷入 MIBIB (mtd1) ==="
eval $SSH_CMD root@$IP "
    mtd erase /dev/mtd1
    mtd write /tmp/ax6-mibib-stock.bin /dev/mtd1
"

echo "=== 刷入 Uboot (mtd7) ==="
eval $SSH_CMD root@$IP "
    mtd erase /dev/mtd7
    mtd write /tmp/ax6-uboot-stock.bin /dev/mtd7
    sync
"

echo ""
echo "刷入完成！请断电重启路由器。"
echo ""
echo "重启后通过 uboot web UI (192.168.1.1) 上传完整 OpenWRT 固件。"
