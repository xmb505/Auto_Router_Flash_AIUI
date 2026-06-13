#!/usr/bin/env bash
# set_miwifi_uboot_partition.sh — AX3600 切启动分区
#
# 3 个 nvram / fw_setenv flag 互补设置:
#   --part 0 → 切到 mtd12 (rootfs)
#   --part 1 → 切到 mtd13 (rootfs_1)
#
# 本脚本智能检测: stock 下用 nvram, OpenWrt 下用 fw_setenv
#
# 用法:
#   ./set_miwifi_uboot_partition.sh --part 0      # 切到 mtd12
#   ./set_miwifi_uboot_partition.sh --part 1      # 切到 mtd13

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh_ip="192.168.31.1"
ssh_pwd="root"
part=""
debug=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ssh_ip="${2:-}"; shift 2 ;;
    --ssh-pwd) ssh_pwd="${2:-}"; shift 2 ;;
    --part)    part="${2:-}"; shift 2 ;;
    --debug)   debug=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) printf '{"ok":false,"error":"未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

if [ -z "$part" ]; then
  echo '{"ok":false,"error":"--part 必传 (0=mtd12 或 1=mtd13)"}'
  exit 2
fi
case "$part" in
  0|1) ;;
  *) printf '{"ok":false,"error":"--part 必须是 0 或 1, 实际: %s"}\n' "$part"; exit 2 ;;
esac

# 三互补 flag: 切到 mtd12 (rootfs) vs mtd13 (rootfs_1)
case "$part" in
  0) f1="0"; f2="1"; fb="0" ;;  # mtd12: sys1 ok, sys2 failed
  1) f1="1"; f2="0"; fb="1" ;;  # mtd13: sys1 failed, sys2 ok
esac

# 强制走远程 SSH (miwifi_ssh.sh), 不检测本地工具
"$SCRIPT_DIR/miwifi_ssh.sh" --ip "$ssh_ip" --pwd "$ssh_pwd" \
  --cmd "nvram set flag_try_sys1_failed=${f1}; nvram set flag_try_sys2_failed=${f2}; nvram set flag_boot_rootfs=${fb}; nvram commit" \
  2>/dev/null | python3 -c "
import sys,json
arr=json.load(sys.stdin)
if arr and arr[0].get('ok'):
    print(json.dumps({'ok':True,'ip':'${ssh_ip}','part':${part},
        'flags':{'flag_try_sys1_failed':'${f1}','flag_try_sys2_failed':'${f2}','flag_boot_rootfs':'${fb}'},
        'next_step':'reboot 激活: ./miwifi_ssh.sh --cmd reboot 或物理 reset'}))
else:
    print(json.dumps({'ok':False,'error':'nvram 设置失败'}))
" 2>/dev/null || echo '{"ok":false,"error":"连接失败"}'
