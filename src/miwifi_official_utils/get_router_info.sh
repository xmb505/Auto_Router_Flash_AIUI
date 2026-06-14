#!/bin/bash
# get_router_info.sh — 小米路由器信息查询（init_info 端点，无需鉴权）
#
# 适用: 所有暴露 /cgi-bin/luci/api/xqsystem/init_info 的小米路由器
# 用法: ./get_router_info.sh [--ip 192.168.31.1]
#
# 输出: JSON（直接透传路由器响应，无额外包装）
#       字段含 inited, romversion, routername, serial, mac, model 等

ip="192.168.31.1"
[ "$1" = "--ip" ] && [ -n "$2" ] && ip="$2"
curl -s --connect-timeout 3 "http://${ip}/cgi-bin/luci/api/xqsystem/init_info"
