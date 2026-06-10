#!/usr/bin/env bash
# router_official_recovery.sh — 官方系统重置（Official System Reset）
#
# 适用: 小米路由器（任何暴露 /api/xqsystem/reset 端点的机型）
# 前置: 已初始化 + 已登录获得 stok（来源: ./2.login_get_stok.py）
# 危险: 路由器所有配置 / 账户 / Wi-Fi 立即抹除，设备自动重启
# 重启耗时: AX6 实测约 2~3 分钟后重新上线，回到出厂态（inited=0）
# 机制: GET /cgi-bin/luci/;stok=<stok>/api/xqsystem/reset?format=0
#        format=0 = 仅重置 NVRAM 配置（保留 user_data 分区）
#
# 设计哲学: 默认静默（Rule of Silence），--debug 显式开日志
#           exit 0 = 成功 / 1 = 路由器拒绝 / 2 = 参数错 / 3 = 网络错

set -euo pipefail

DEFAULT_IP="192.168.31.1"
ip="$DEFAULT_IP"
stok=""
debug=0

usage() {
    cat <<'EOF'
router_official_recovery.sh — 官方系统重置（Official System Reset）

通过小米固件自带的官方 API 将路由器配置一键重置。

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

复位后（本脚本 exit 0 之后）:
  路由器立即重启，重启期间完全不可达（curl 超时 / 连接拒绝）。
  重启完毕回到出厂态，init/inited 变为 0。
  AX6 实测完成约需 2~3 分钟，可用 get_router_info.sh 轮询确认上线。

  复位后出厂默认:
    - 管理密码: admin
    - Wi-Fi: SSID=routername（MAC 派生值）, 无密码或默认密码
    - 绑定状态: 未绑定小米账号
    - 固件版本: 不变（reset 不清固件区）

  上线后 init_info 响应长这样:
    {"inited":0, "romversion":"1.1.10", "routername":"Redmi_E0B9_1F46", ...}
  inited=0 → 出厂态；inited=1 → 已初始化。

返回:
  0 = 成功（默认无 stdout 输出；--debug 显示 HTTP 200 + {"code":0}）
  1 = 路由器拒绝 / HTTP 错误（stderr 带 body）
  2 = 参数错误
  3 = 网络错误（无法连接路由器）
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

# 一次请求带回 body + 状态码，body 在 stderr 之前/之后分两行写入变量
# 用临时文件避免 subshell 变量丢失
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

# 小米 API 层错误（成功响应: {"code":0}）
code=$(printf '%s' "$body" \
       | grep -oE '"code"[[:space:]]*:[[:space:]]*[0-9]+' \
       | grep -oE '[0-9]+$' || true)
code="${code:-?}"
if [ "$code" != "0" ]; then
    echo "路由器拒绝 (code=${code}): ${body}" >&2
    exit 1
fi

# 成功：默认静默
exit 0
