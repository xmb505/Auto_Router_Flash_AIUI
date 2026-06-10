#!/bin/bash
# 5.check_boot_partition.sh — 检测 AX6 当前启动分区（不依赖 nvram）
# 权威来源: /proc/cmdline  交叉验证: mount, /sys/class/ubi, nvram flag_boot_rootfs
# 完成后输出 JSON（成功 ok=true / 失败 ok=false，免看退出码）
# 默认静默；--debug 详细探测
#
# 用法: ./5.check_boot_partition.sh [选项]
# 可选: --ip <IP>              默认 192.168.31.1
#       --ssh-pwd <密码>        默认 root
#       --debug                详细探测过程
#       -h, --help             显示本帮助
#
# 依赖: 同目录的 miwifi_ssh.sh（SSH 连接复用）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIWIFI_SSH="$SCRIPT_DIR/miwifi_ssh.sh"

ip="192.168.31.1"
ssh_pwd="root"
debug=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ip="${2:-}"; shift 2 ;;
    --ssh-pwd) ssh_pwd="${2:-}"; shift 2 ;;
    --debug)   debug=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *)         printf '{"ok": false, "error": "未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

# 构造远端 payload（4 段命令用 --- 分隔）
build_payload() {
  cat <<'EOF'
cat /proc/cmdline
echo "---"
mount | grep "on / "
echo "---"
for v in /sys/class/ubi/ubi*_*/; do
  [ -f "${v}name" ] && echo "${v}name=$(cat ${v}name)"
done
echo "---"
nvram get flag_boot_rootfs
EOF
}

# debug 模式：人眼友好输出
if [ "$debug" = 1 ]; then
  "$MIWIFI_SSH" --ip "$ip" --pwd "$ssh_pwd" --cmd "$(build_payload)" \
    | python3 -c "
import sys, json
arr = json.load(sys.stdin)
for r in arr:
    print(r['stdout'], end='')
    if r['stderr']:
        print('STDERR:', r['stderr'], file=sys.stderr)
"
  exit $?
fi

# 默认：跑 + 解析
raw=$("$MIWIFI_SSH" --ip "$ip" --pwd "$ssh_pwd" --cmd "$(build_payload)" 2>/dev/null)

# 提取 miwifi_ssh 返回的 stdout 字段
raw_stdout=$(echo "$raw" | python3 -c "
import sys, json
arr = json.load(sys.stdin)
print(arr[0]['stdout'] if arr and arr[0].get('ok') else '')
" 2>/dev/null)

if [ -z "$raw_stdout" ]; then
  echo '{"ok": false, "error": "无法连接路由器或命令失败"}'
  exit 1
fi

# 按 "---" 拆 4 段
declare -A sections
i=0
while IFS= read -r line; do
  if [ "$line" = "---" ]; then
    ((i++))
  else
    sections[$i]+="$line"$'\n'
  fi
done <<< "$raw_stdout"

cmdline=$(printf '%s' "${sections[0]}" | head -1)
mount_src=$(printf '%s' "${sections[1]}" | head -1)
ubi_info=$(printf '%s' "${sections[2]}" | tr '\n' ';' | sed 's/;$//')
nvram_flag=$(printf '%s' "${sections[3]}" | head -1)

# 当前启动分区（cmdline 权威）
current=$(echo "$cmdline" | grep -oE 'ubi\.mtd=[^ ]+' | head -1 | cut -d= -f2)
case "$current" in
  rootfs)   mtd="mtd12" ;;
  rootfs_1) mtd="mtd13" ;;
  *)        mtd="unknown" ;;
esac

# next_boot 推测（nvram）
case "$nvram_flag" in
  0) next_boot="rootfs" ;;
  1) next_boot="rootfs_1" ;;
  *) next_boot="unknown" ;;
esac

# 一致性
[ "$current" = "$next_boot" ] && consistency="true" || consistency="false"

# 输出 JSON
printf '{"ok": true, "current_partition": "%s", "current_mtd": "%s", "next_boot_intent": "%s", "consistency": %s, "cmdline_ubi_mtd": "%s", "mount_source": "%s", "nvram_flag_boot_rootfs": "%s", "ubi_info": "%s"}\n' \
  "$current" "$mtd" "$next_boot" "$consistency" \
  "$(echo "$cmdline" | grep -oE 'ubi\.mtd=[^ ]+' | head -1)" \
  "$mount_src" \
  "$nvram_flag" \
  "$ubi_info"
