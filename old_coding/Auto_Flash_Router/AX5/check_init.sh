#!/bin/bash

ROUTE_IP="${1:-192.168.31.1}"
LOCATION=$(curl -s --connect-timeout 3 -o /dev/null -w '%{redirect_url}' "http://${ROUTE_IP}/cgi-bin/luci/web" 2>/dev/null)

if [[ -z "$LOCATION" ]]; then
    echo '{"init":-1,"error":"路由器不可达"}'
elif [[ "$LOCATION" == *"/init.html"* ]]; then
    echo '{"init":1}'
else
    echo '{"init":0}'
fi