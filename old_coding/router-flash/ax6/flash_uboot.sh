#!/bin/bash
# Stage 3: 刷 MIBIB (分区表) + Uboot
# 在过渡 OpenWRT (192.168.1.1, 免密 SSH) 中执行
# 官方参考: 刷机流程.md

IP="${IP:-192.168.1.1}"
DIR="files/openwrt"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"

_ssh() {
    ssh $SSH_OPTS "$@"
}

_scp() {
    scp -O $SSH_OPTS "$@"
}

# 1. 上传文件
echo "=== 上传 MIBIB + Uboot ==="
_scp "$DIR/ax6-mibib-stock.bin" root@$IP:/tmp/
_scp "$DIR/ax6-uboot-stock.bin" root@$IP:/tmp/

# 2. MD5 校验
echo "=== MD5 校验 ==="
for f in ax6-mibib-stock.bin ax6-uboot-stock.bin; do
    LOCAL=$(md5sum "$DIR/$f" | cut -d' ' -f1)
    REMOTE=$(_ssh root@$IP "md5sum /tmp/$f" | cut -d' ' -f1)
    echo "  $f: local=$LOCAL remote=$REMOTE"
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "MD5 不匹配"; exit 1
    fi
done

# 3. 刷写 MIBIB (mtd1)
echo "=== 刷入 MIBIB (mtd1) ==="
_ssh root@$IP "mtd erase /dev/mtd1 && mtd write /tmp/ax6-mibib-stock.bin /dev/mtd1"

# 4. 刷写 Uboot (mtd7)
echo "=== 刷入 Uboot (mtd7) ==="
_ssh root@$IP "mtd erase /dev/mtd7 && mtd write /tmp/ax6-uboot-stock.bin /dev/mtd7 && sync"

echo ""
echo "=== 刷入完成！==="
echo "路由器正在重启进入 uboot 模式..."
_ssh root@$IP 'reboot' 2>/dev/null || true