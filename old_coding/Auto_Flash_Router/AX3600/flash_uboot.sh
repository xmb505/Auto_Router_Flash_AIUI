#!/bin/bash
# 刷入自定义 MIBIB (分区表) + Uboot
# 用法: ./flash_uboot.sh

set -e

IP="192.168.1.1"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"
DIR="file/openwrt"

echo "=== 上传 MIBIB + Uboot ==="
sshpass -p '' scp -O $SSH_OPTS "$DIR/ax3600-mibib.bin" root@$IP:/tmp/
sshpass -p '' scp -O $SSH_OPTS "$DIR/ax3600-uboot.bin" root@$IP:/tmp/

echo "=== MD5 校验 ==="
for f in ax3600-mibib.bin ax3600-uboot.bin; do
    LOCAL=$(md5sum "$DIR/$f" | cut -d' ' -f1)
    REMOTE=$(ssh $SSH_OPTS root@$IP "md5sum /tmp/$f" | cut -d' ' -f1)
    echo "  $f: local=$LOCAL remote=$REMOTE"
    [ "$LOCAL" = "$REMOTE" ] || { echo "MD5 不匹配"; exit 1; }
done

echo "=== 刷入 MIBIB (mtd1) ==="
ssh $SSH_OPTS root@$IP "
    mtd erase /dev/mtd1
    mtd write /tmp/ax3600-mibib.bin /dev/mtd1
"

echo "=== 刷入 Uboot (mtd7) ==="
ssh $SSH_OPTS root@$IP "
    mtd erase /dev/mtd7
    mtd write /tmp/ax3600-uboot.bin /dev/mtd7
    sync
"

echo "刷入完成，请断电重启路由器"
