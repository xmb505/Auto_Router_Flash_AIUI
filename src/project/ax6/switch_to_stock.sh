#!/usr/bin/env bash
# switch_to_stock.sh — OpenWrt → 小米 stock (切启动分区 + reboot)
#
# OpenWrt 下没有 nvram, 用 fw_setenv 写 uboot env flag,
# 让下次启动从 mtd12 (rootfs) 进小米 stock 固件。
#
# 使用:
#   ./switch_to_stock.sh                      # 默认 192.168.1.1
#   ./switch_to_stock.sh --ip 192.168.1.1     # 指定 IP
#
# 输出: stdout = JSON, exit 0 = 成功

set -euo pipefail

IP="192.168.1.1"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip) IP="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $(basename "$0") [--ip <路由器IP>]"
            exit 0 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

# SSH 到 OpenWrt 切 flag + reboot
# root 免密 / 无密码 (ImmortalWrt 默认)
OUTPUT=$(sshpass -p "" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@${IP}" \
    "fw_setenv flag_try_sys1_failed 0 && fw_setenv flag_boot_rootfs 0 && echo OK_REBOOT && reboot" 2>&1)

if echo "$OUTPUT" | grep -q "OK_REBOOT"; then
    echo '{"ok":true,"ip":"'"${IP}"'","action":"switch_to_stock","next_ip":"192.168.31.1"}'
    exit 0
else
    echo '{"ok":false,"ip":"'"${IP}"'","action":"switch_to_stock","error":"'"${OUTPUT}"'"}'
    exit 1
fi
