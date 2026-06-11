#!/usr/bin/env bash
# router_official_recovery.sh — 官方系统重置（Official System Reset）
#
# 适用: CR660X (stock 固件, nginx/1.12.2, xqsystem 体系; 联通/移动/电信版 API 一致)
# 前置: 已初始化 + 已登录获得 stok（来源: ./2.login_get_stok.py）
# 危险: 路由器所有配置 / 账户 / Wi-Fi 立即抹除，设备自动重启
# 机制: GET /cgi-bin/luci/;stok=<stok>/api/xqsystem/reset?format=0
#        format=0 = 仅重置 NVRAM 配置（保留 user_data 分区）
#        无 /reset.html 页面（404），无 magic 字段
#
# 设计哲学: 默认静默（Rule of Silence），--debug 显式开日志
#           exit 0 = 成功 / 1 = 路由器拒绝 / 2 = 参数 / 3 = 网络

set -euo pipefail

DEFAULT_IP="192.168.31.1"   # CR6608 默认；CR6606 联通版一般 192.168.1.1
ip="$DEFAULT_IP"
stok=""
debug=0

usage() {
    cat <<'EOF'
router_official_recovery.sh — 官方系统重置（Official System Reset）

通过小米/红米固件自带的官方 API 将路由器配置一键重置。
pb-boot 引导（nginx/1.12.2）+ 小米 xqsystem 体系。

用法:
  ./router_official_recovery.sh --stok <token> [--ip IP] [--debug]

必传:
  --stok <token>     登录拿到的 stok 令牌（来源: ./2.login_get_stok.py）

可选:
  --ip <IP>          路由器 IP（默认: 192.168.31.1）
  --debug            打印请求详情到 stderr
  -h, --help         显示本帮助

危险操作:
  路由器所有配置 / 账户 / Wi-Fi 立即抹除，设备自动重启。
  format=0 = 仅重置 NVRAM 配置（保留 user_data 分区）。

复位后:
  路由器立即重启，重启期间完全不可达（curl 超时 / 连接拒绝）。
  重启完毕回到出厂态，init/inited 变为 0。

  复位后出厂默认:
    - 管理密码: admin
    - 联通版默认 IP: 192.168.1.1（移动版 192.168.31.1）
    - 固件版本: 不变（reset 不清固件区）

  上线后 init_info 响应长这样:
    {"inited":0, "romversion":"1.0.117", "routername":"Xiaomi_...", ...}
  inited=0 → 出厂态；inited=1 → 已初始化。

返回:
  0 = 成功
  1 = 路由器拒绝 / HTTP 错误（stderr 带 body）
  2 = 参数错误
  3 = 网络错误
EOF
}

# ============ 参数解析 ============
while [ $# -gt 0 ]; do
    case "$1" in
        --stok)        stok="${2:-}"; shift 2 ;;
        --ip)          ip="${2:-}";   shift 2 ;;
        --debug)       debug=1;        shift   ;;
        -h|--help)     usage; exit 0               ;;
        *)             echo "未知参数: $1" >&2
                       echo "用法: $0 --stok <token> [--ip IP] [--debug]" >&2
                       exit 2                       ;;
    esac
done

# ============ 校验 ============
if [ -z "$stok" ]; then
    echo "错误: --stok 必传" >&2
    exit 2
fi

# ============ 执行 ============
url="http://${ip}/cgi-bin/luci/;stok=${stok}/api/xqsystem/reset?format=0"
[ "$debug" = 1 ] && echo "[DEBUG] GET ${url}" >&2

# 一次请求带回 body + 状态码
tmp_body=$(mktemp)
trap 'rm -f "$tmp_body"' EXIT

http_code=$(curl -sS --connect-timeout 5 -m 15 \
    -o "$tmp_body" -w '%{http_code}' "$url") || {
    echo "网络错误: 无法连接 ${ip}" >&2
    exit 3
}

body=$(cat "$tmp_body")
[ "$debug" = 1 ] && echo "[DEBUG] HTTP ${http_code}: ${body}" >&2

# HTTP 层错误
if [ "$http_code" != "200" ]; then
    echo "HTTP ${http_code}: ${body}" >&2
    exit 1
fi

# 小米 API 层错误（成功响应: {"code":0}，空 body 也可能）
code=$(printf '%s' "$body" \
       | grep -oE '"code"[[:space:]]*:[[:space:]]*[0-9]+' \
       | grep -oE '[0-9]+$' || true)
if [ -n "$code" ] && [ "$code" != "0" ]; then
    echo "路由器拒绝 (code=${code}): ${body}" >&2
    exit 1
fi

# 成功：默认静默
exit 0
