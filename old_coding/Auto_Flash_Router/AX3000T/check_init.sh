#!/bin/bash

ROUTE_IP="${1:-192.168.31.1}"
RESULT=$(curl -s --connect-timeout 3 "http://${ROUTE_IP}/cgi-bin/luci/api/xqsystem/init_info" 2>/dev/null)

if [[ -z "$RESULT" ]]; then
    echo '{"init":-1,"error":"路由器不可达"}'
elif echo "$RESULT" | grep -q '"inited":0'; then
    echo '{"init":1}'
else
    echo '{"init":0}'
fi