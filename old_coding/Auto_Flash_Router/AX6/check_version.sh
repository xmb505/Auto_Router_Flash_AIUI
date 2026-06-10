#!/bin/bash
ROUTE_IP="${1:-192.168.31.1}"
curl -s "http://${ROUTE_IP}/cgi-bin/luci/api/xqsystem/init_info" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('romversion','unknown'))"
