#!/bin/bash
# check_cr660x_ip_online.sh — 检测 CR660X 五个厂商默认 IP 哪个在线
#
# 用法: ./check_cr660x_ip_online.sh
#       ./check_cr660x_ip_online.sh --timeout 60
#       ./check_cr660x_ip_online.sh --debug
#
# 默认 timeout: 180 秒（3 分钟）
# 五个 IP 并行 ping，先响应的就是在线 IP
#
# 输出: stdout = 单个 JSON {"ok": true/false, "found_ip": "..."}
#       exit  = 0 找到 / 1 超时

IPS=("192.168.1.1" "192.168.2.1" "10.11.12.1" "192.168.10.1" "192.168.31.1")
TIMEOUT=180
DEBUG=0

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT="${2:-180}"; shift 2 ;;
    --debug)   DEBUG=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *)         printf '{"ok":false,"error":"未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

# 并行 ping：每个 IP 一个后台进程，ping 通则写标记文件
tmpdir=$(mktemp -d) || exit 1
trap "rm -rf $tmpdir" EXIT

for ip in "${IPS[@]}"; do
  (
    while true; do
      if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
        touch "$tmpdir/$ip"
        exit 0
      fi
      sleep 1
    done
  ) &
done

[ "$DEBUG" = 1 ] && printf "检测 %s ...（超时 %ds）\n" "${IPS[*]}" "$TIMEOUT" >&2

end=$((SECONDS + TIMEOUT))
found=""
while [ $SECONDS -lt $end ]; do
  for ip in "${IPS[@]}"; do
    if [ -f "$tmpdir/$ip" ]; then
      found="$ip"
      break 2
    fi
  done
  sleep 1
done

kill $(jobs -p) 2>/dev/null
wait 2>/dev/null

if [ -n "$found" ]; then
  printf '{"ok":true,"found_ip":"%s"}\n' "$found"
  exit 0
fi

printf '{"ok":false,"found_ip":null,"error":"超时 %ds，五个 IP 均无响应"}\n' "$TIMEOUT"
exit 1
