#!/bin/bash
# 在过渡 OpenWRT 中设置启动标志，为刷 uboot / 大分区做准备
# 用法: bash control_openwrt.sh

set -e
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.1 "
    fw_setenv flag_last_success 0
    fw_setenv flag_boot_rootfs 0
"
echo "标志已设置"
