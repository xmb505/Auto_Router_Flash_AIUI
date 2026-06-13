#!/bin/bash
# openwrt_modern_standart_ssh.sh — 一键 SSH 到 OpenWrt 路由器（现代 Dropbear/OpenSSH，不需 ssh-rsa hack）
#
# 两种模式:
#   1. 交互式: ./openwrt_modern_standart_ssh.sh
#   2. 命令式: ./openwrt_modern_standart_ssh.sh --cmd 'uname -a'
#              ./openwrt_modern_standart_ssh.sh --cmd 'cmd1' --cmd 'cmd2'  # JSON 数组
#
# 通用开关:
#   --ip <IP>              默认 192.168.1.1
#   --user <用户名>         默认 root
#   --pwd <密码>            默认 admin
#   --cmd '<command>'       跑命令后返回 JSON（可重复传多条）
#   -h, --help             显示本帮助

ip="192.168.1.1"
user="root"
pwd="admin"
cmds=()

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)       ip="${2:-}"; shift 2 ;;
    --user)     user="${2:-}"; shift 2 ;;
    --pwd)      pwd="${2:-}"; shift 2 ;;
    --cmd)      cmds+=("${2:-}"); shift 2 ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *)          echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

json_str() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"; s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

if [ ${#cmds[@]} -gt 0 ]; then
  out_file=$(mktemp); err_file=$(mktemp)
  trap "rm -f $out_file $err_file" EXIT

  first=1
  printf '['
  for cmd in "${cmds[@]}"; do
    sshpass -p "$pwd" ssh \
      -oStrictHostKeyChecking=no \
      -oUserKnownHostsFile=/dev/null \
      -oLogLevel=ERROR \
      "${user}@${ip}" "$cmd" > "$out_file" 2> "$err_file"
    ec=$?
    out=$(cat "$out_file"); err=$(cat "$err_file")
    ok=$([ $ec -eq 0 ] && echo true || echo false)

    [ $first -eq 0 ] && printf ','
    printf '{"ok":%s,"cmd":%s,"exit_code":%d,"stdout":%s,"stderr":%s}' \
      "$ok" "$(json_str "$cmd")" "$ec" "$(json_str "$out")" "$(json_str "$err")"
    first=0
  done
  printf ']\n'
  exit 0
fi

exec sshpass -p "$pwd" ssh \
  -oStrictHostKeyChecking=no \
  -oUserKnownHostsFile=/dev/null \
  -oLogLevel=ERROR \
  -tt \
  "${user}@${ip}"
