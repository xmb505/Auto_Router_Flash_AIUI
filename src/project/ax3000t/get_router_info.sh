#!/bin/bash
# AX6 路由器信息查询 — init_info 端点（无需鉴权）
# 用法: ./get_router_info.sh [--ip 192.168.31.1]

ip="192.168.31.1"
[ "$1" = "--ip" ] && [ -n "$2" ] && ip="$2"
curl -s --connect-timeout 3 "http://${ip}/cgi-bin/luci/api/xqsystem/init_info"
