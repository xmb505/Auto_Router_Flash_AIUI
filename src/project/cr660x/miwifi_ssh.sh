#!/bin/bash
# miwifi_ssh.sh — 一键 SSH 到 CR660X 路由器（连接复用组件）
#
# 两种模式:
#   1. 交互式: ./miwifi_ssh.sh                  启动 SSH shell（exec 替换）
#   2. 命令式: ./miwifi_ssh.sh --cmd 'nvram get foo'   跑单条命令，返回 JSON
#              ./miwifi_ssh.sh --cmd 'cmd1' --cmd 'cmd2'  多条独立返回 JSON 数组
#
# 通用开关:
#   --ip <IP>              默认 192.168.31.1 (CR6608 / 改了 IP 的 CR6606)
#                          CR6606 联通版原始 IP 是 192.168.1.1
#   --pwd <密码>            默认 root（3.enable_ssh.py 实测设的密码）
#   --cmd '<command>'       跑命令后返回 JSON（可重复传多条）
#   -h, --help             显示本帮助
#
# 依赖: sshpass
#
# 来源: ax6/miwifi_ssh.sh（同样的 dropbear ssh-rsa 限制 + 同款工具契约）
#
# JSON 字段（每条命令）:
#   {"ok": bool, "cmd": "原命令", "exit_code": int, "stdout": "...", "stderr": "..."}

ip="192.168.31.1"
ssh_pwd="root"
cmds=()

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ip="${2:-}"; shift 2 ;;
    --pwd)     ssh_pwd="${2:-}"; shift 2 ;;
    --cmd)     cmds+=("${2:-}"); shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *)         echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# JSON 字符串转义（处理 \ " 换行 tab）
json_str() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

if [ ${#cmds[@]} -gt 0 ]; then
  # 命令模式：每条独立跑 SSH，返回 JSON 数组
  out_file=$(mktemp); err_file=$(mktemp)
  trap "rm -f $out_file $err_file" EXIT

  first=1
  printf '['
  for cmd in "${cmds[@]}"; do
    sshpass -p "$ssh_pwd" ssh \
      -oHostKeyAlgorithms=+ssh-rsa \
      -oStrictHostKeyChecking=no \
      -oUserKnownHostsFile=/dev/null \
      -oLogLevel=ERROR \
      "root@${ip}" "$cmd" > "$out_file" 2> "$err_file"
    ec=$?
    out=$(cat "$out_file")
    err=$(cat "$err_file")
    ok=$([ $ec -eq 0 ] && echo true || echo false)

    [ $first -eq 0 ] && printf ','
    printf '{"ok":%s,"cmd":%s,"exit_code":%d,"stdout":%s,"stderr":%s}' \
      "$ok" "$(json_str "$cmd")" "$ec" "$(json_str "$out")" "$(json_str "$err")"
    first=0
  done
  printf ']\n'
  exit 0
fi

# 交互式模式：exec 替换 shell，TTY/Ctrl-C 行为最干净
exec sshpass -p "$ssh_pwd" ssh \
  -oHostKeyAlgorithms=+ssh-rsa \
  -oStrictHostKeyChecking=no \
  -oUserKnownHostsFile=/dev/null \
  -oLogLevel=ERROR \
  -tt \
  "root@${ip}"
