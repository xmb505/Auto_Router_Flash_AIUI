#!/bin/bash
# set_uboot_env.sh — 批量设 nvram flags，自动 commit
# 适用: 刷机准备阶段（让 uboot 等 tftp、SSH/telnet/UART 全开、boot 标志归位）
#       或后续刷机脚本切换 rootfs 启动（--set flag_boot_rootfs=0/1）
# 完成后输出 JSON（成功 ok=true / 失败 ok=false，免看退出码）
# 默认静默；--debug 详细
#
# 用法:
#   ./set_uboot_env.sh                                  跑默认 8 个 key（刷机准备）
#   ./set_uboot_env.sh --set flag_boot_rootfs=1         切换下次启动到备胎
#   ./set_uboot_env.sh --set foo=bar --set baz=qux     多个自定义 key
#
# 通用开关:
#   --ip <IP>              默认 192.168.31.1
#   --ssh-pwd <密码>        默认 root
#   --debug                详细探测过程
#   -h, --help             显示本帮助
#
# 依赖: 同目录的 miwifi_ssh.sh（SSH 连接复用组件）
# 副作用: 改写路由器 nvram 并 commit 写 flash。**有破坏性**。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIWIFI_SSH="$SCRIPT_DIR/miwifi_ssh.sh"

ip="192.168.31.1"
ssh_pwd="root"
debug=0
custom_sets=()

# 默认 8 个 key（按老版本刷机流程.md 推荐）
DEFAULT_KEYS=(
  "flag_last_success=0"
  "flag_boot_success=1"
  "flag_try_sys1_failed=0"
  "flag_try_sys2_failed=0"
  "boot_wait=on"
  "uart_en=1"
  "telnet_en=1"
  "ssh_en=1"
)

# key 名合法：字母/数字/下划线，字母或下划线开头
KEY_REGEX='^[a-zA-Z_][a-zA-Z0-9_]*=.*$'

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ip="${2:-}"; shift 2 ;;
    --ssh-pwd) ssh_pwd="${2:-}"; shift 2 ;;
    --set)
      kv="${2:-}"
      if [ -z "$kv" ]; then
        printf '{"ok": false, "error": "--set 缺值"}\n'
        exit 2
      fi
      if [[ ! "$kv" =~ $KEY_REGEX ]]; then
        printf '{"ok": false, "error": "--set 格式错误: %s (期望 name=value，name 由字母/数字/下划线组成)"}\n' "$kv"
        exit 2
      fi
      custom_sets+=("$kv")
      shift 2
      ;;
    --debug)   debug=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *)         printf '{"ok": false, "error": "未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

# 选模式：有 --set → custom；无 → default
if [ ${#custom_sets[@]} -gt 0 ]; then
  sets=("${custom_sets[@]}")
  mode="custom"
else
  sets=("${DEFAULT_KEYS[@]}")
  mode="default"
fi

# 跑远端命令（复用 miwifi_ssh.sh 的 SSH 配置）
# 拿 stdout/stderr/exit_code
ssh_run() {
  local cmd="$1"
  "$MIWIFI_SSH" --ip "$ip" --pwd "$ssh_pwd" --cmd "$cmd" 2>/dev/null
}

# 构造 set 段和 verify 段
build_set_script() {
  for kv in "${sets[@]}"; do
    printf 'nvram set %q || { echo SET_FAIL:%s; exit 1; }\n' "$kv" "$kv"
  done
  echo 'nvram commit || { echo COMMIT_FAIL; exit 1; }'
}

build_verify_script() {
  for kv in "${sets[@]}"; do
    k="${kv%%=*}"
    cat <<EOF
printf 'VERIFY:${k}=%s\n' "\$(nvram get ${k})"
EOF
  done
}

run_remote() {
  local payload
  payload="$(build_set_script)
echo '---'
$(build_verify_script)"
  ssh_run "$payload"
}

if [ "$debug" = 1 ]; then
  echo "=== 模式: $mode ==="
  echo "=== 将要 set + commit ==="
  build_set_script
  echo ""
  echo "=== 在路由器上执行 ==="
  run_remote | python3 -c "
import sys, json
arr = json.load(sys.stdin)
for r in arr:
    print(r['stdout'], end='')
"
  exit $?
fi

# 默认：跑 + 抓 verify
raw=$(run_remote)
# raw 形如 [{"ok":true,"cmd":"...","stdout":"...","stderr":""}]
# 提取 stdout 字段
raw_stdout=$(echo "$raw" | python3 -c "
import sys, json
arr = json.load(sys.stdin)
print(arr[0]['stdout'] if arr else '')
" 2>/dev/null)

if [ -z "$raw_stdout" ]; then
  echo '{"ok": false, "error": "无法连接路由器或命令失败"}'
  exit 1
fi

# 失败检查
if echo "$raw_stdout" | grep -q "SET_FAIL:"; then
  fk=$(echo "$raw_stdout" | grep -oE 'SET_FAIL:[^[:space:]]*' | head -1 | cut -d: -f2)
  printf '{"ok": false, "error": "nvram set 失败", "failed_key": "%s"}\n' "$fk"
  exit 1
fi
if echo "$raw_stdout" | grep -q "COMMIT_FAIL"; then
  echo '{"ok": false, "error": "nvram commit 失败"}'
  exit 1
fi

# 解析 verify 段
verified_block=$(echo "$raw_stdout" | sed -n '/^---$/,$p' | sed '1d')

# 构造 JSON
set_json=""
vjson=""
first=1
for kv in "${sets[@]}"; do
  k="${kv%%=*}"; v="${kv#*=}"
  if [ "$first" = 1 ]; then
    set_json="\"$k\": \"$v\""
    first=0
  else
    set_json="$set_json, \"$k\": \"$v\""
  fi
  actual=$(echo "$verified_block" | grep -oE "VERIFY:${k}=[^\|]*" | head -1 | cut -d= -f2-)
  vjson="${vjson:+$vjson, }\"$k\": \"$actual\""
done

printf '{"ok": true, "mode": "%s", "ip": "%s", "set": {%s}, "verified": {%s}}\n' \
  "$mode" "$ip" "$set_json" "$vjson"
