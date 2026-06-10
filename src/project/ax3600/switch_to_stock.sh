#!/usr/bin/env bash
# switch_to_stock.sh — OpenWrt → 小米 stock (AX3600)
#
# OpenWrt 下用 fw_setenv 写 uboot env flag 切到 mtd12 (rootfs / stock).
# 3 个 flag 互补设置 + reboot, 与 6.miwifi_2_openwrt.py 的切 flag 逻辑一致.
#
# 使用:
#   ./switch_to_stock.sh                      # 默认 192.168.1.1
#   ./switch_to_stock.sh --ip 192.168.1.1     # 指定 IP

set -euo pipefail

IP="192.168.1.1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip) IP="$2"; shift 2 ;;
    -h|--help)
      echo "用法: $(basename "$0") [--ip <路由器IP>]"
      echo "OpenWrt 上通过 fw_setenv 3 个 flag 切到 mtd12 (stock)"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

OUTPUT=$(sshpass -p "" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@${IP}" \
    "fw_setenv flag_try_sys1_failed 0 && \
     fw_setenv flag_try_sys2_failed 1 && \
     fw_setenv flag_boot_rootfs 0 && \
     echo FLAGS_OK && \
     reboot" 2>&1)

if echo "$OUTPUT" | grep -q "FLAGS_OK"; then
  echo '{"ok":true,"ip":"'"${IP}"'","action":"switch_to_stock (mtd13→mtd12)","next_ip":"192.168.31.1"}'
  exit 0
else
  echo '{"ok":false,"ip":"'"${IP}"'","action":"switch_to_stock","error":"'"${OUTPUT}"'"}'
  exit 1
fi
