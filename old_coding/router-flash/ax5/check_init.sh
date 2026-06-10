#!/bin/bash

ROUTE_IP="${1:-192.168.31.1}"
RESULT=$(curl -s --connect-timeout 3 "http://${ROUTE_IP}/cgi-bin/luci/api/xqsystem/init_info" 2>/dev/null)

if [[ -z "$RESULT" ]]; then
    echo '{"init":-1,"error":"路由器不可达"}'
elif echo "$RESULT" | python3 -c "import sys,json; exit(0 if json.load(sys.stdin).get('inited')==1 else 1)" 2>/dev/null; then
    echo '{"init":0}'
else
    echo '{"init":1}'
fi
