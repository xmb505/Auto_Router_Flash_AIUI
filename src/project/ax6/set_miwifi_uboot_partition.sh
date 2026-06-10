#!/bin/bash
# set_miwifi_uboot_partition.sh — 单纯切启动分区
# (3 个 flag 互补设置, 调 miwifi_ssh.sh 复用 SSH 配置)
#
# 切到 part=0 → mtd12 (rootfs_0) 启动
#   flag_try_sys1_failed=0 (sys1 成功)
#   flag_try_sys2_failed=1 (sys2 失败)
#   flag_boot_rootfs=0     (当前在 0)
#
# 切到 part=1 → mtd13 (rootfs_1) 启动
#   flag_try_sys1_failed=1 (sys1 失败)
#   flag_try_sys2_failed=0 (sys2 成功)
#   flag_boot_rootfs=1     (当前在 1)
#
# 用法:
#   ./set_miwifi_uboot_partition.sh --part 0
#   ./set_miwifi_uboot_partition.sh --part 1
#   ./set_miwifi_uboot_partition.sh --part 0 --ip 192.168.1.1  # 当前在 OpenWrt 时
#
# 依赖: 同目录 miwifi_ssh.sh (SSH 复用组件)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIWIFI_SSH="$SCRIPT_DIR/miwifi_ssh.sh"

ip="192.168.31.1"
ssh_pwd="root"
debug=0
part=""

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ip="${2:-}"; shift 2 ;;
    --ssh-pwd) ssh_pwd="${2:-}"; shift 2 ;;
    --part)    part="${2:-}"; shift 2 ;;
    --debug)   debug=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *)         printf '{"ok": false, "error": "未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

# 校验 --part
if [ -z "$part" ]; then
  echo '{"ok": false, "error": "--part 必传 (0 或 1)"}'
  exit 2
fi
case "$part" in
  0|1) ;;
  *) printf '{"ok": false, "error": "--part 必须是 0 或 1, 实际: %s"}\n' "$part"; exit 2 ;;
esac

# 三个 flag 互为互补 (与 6.miwifi_2_openwrt.py 切 flag 逻辑一致)
case "$part" in
  0) f1="0"; f2="1"; fb="0" ;;  # 启动 mtd12
  1) f1="1"; f2="0"; fb="1" ;;  # 启动 mtd13
esac

# 一条 SSH 跑 4 条命令 (复用 miwifi_ssh.sh 的 SSH 配置)
cmd="nvram set flag_try_sys1_failed=${f1}; nvram set flag_try_sys2_failed=${f2}; nvram set flag_boot_rootfs=${fb}; nvram commit"

# --debug 模式
if [ "$debug" = 1 ]; then
  echo "将跑: $cmd" >&2
  "$MIWIFI_SSH" --ip "$ip" --pwd "$ssh_pwd" --cmd "$cmd" 2>&1 | python3 -c "
import sys, json
arr = json.load(sys.stdin)
for r in arr:
    if r['stdout']: print(r['stdout'], end='')
    if r['stderr']: print('STDERR:', r['stderr'], file=sys.stderr)
"
  exit $?
fi

# 默认静默 (2>/dev/null 丢 ssh 警告)
raw=$("$MIWIFI_SSH" --ip "$ip" --pwd "$ssh_pwd" --cmd "$cmd" 2>/dev/null)

# 解析 miwifi_ssh.sh 的输出
ok=$(echo "$raw" | python3 -c "import sys,json; arr=json.load(sys.stdin); print('true' if arr and arr[0].get('ok') else 'false')" 2>/dev/null)

if [ "$ok" != "true" ]; then
  echo '{"ok": false, "error": "nvram 设置失败"}'
  exit 1
fi

# 输出 JSON
printf '{"ok": true, "ip": "%s", "part": %s, "flags": {"flag_try_sys1_failed": "%s", "flag_try_sys2_failed": "%s", "flag_boot_rootfs": "%s"}, "next_step": "reboot 激活: ./miwifi_ssh.sh --cmd reboot 或物理 reset"}\n' \
  "$ip" "$part" "$f1" "$f2" "$fb"
