#!/bin/sh

# ========================================
# 一键覆盖 overlay 到路由器
# 把 overlay-mocktool-10.0.0.1.tar.gz
# 直接解压到路由器的 /overlay 目录
# ========================================

ROUTER_IP="192.168.1.1"
OVERLAY_FILE="files/overlay-mocktool-10.0.0.1.tar.gz"

echo "========================================"
echo "  覆盖 overlay 到路由器 $ROUTER_IP"
echo "========================================"

# 1. 复制文件到路由器
echo ""
echo "[1/3] 复制 overlay 包到路由器..."
scp -o StrictHostKeyChecking=no \
    -O \
    -o UserKnownHostsFile=/dev/null \
    "$OVERLAY_FILE" \
    root@$ROUTER_IP:/tmp/

if [ $? -ne 0 ]; then
    echo "失败！请检查："
    echo "   - 路由器是否已开机且 IP 为 $ROUTER_IP"
    echo "   - SSH 连接是否正常"
    exit 1
fi
echo "  完成"

# 2. 在路由器上解压覆盖 overlay
echo ""
echo "[2/3] 在路由器上解压覆盖 overlay..."
ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    root@$ROUTER_IP << 'ENDSSH'
    cd /overlay
    tar -xzf /tmp/overlay-mocktool-10.0.0.1.tar.gz
    echo "overlay 覆盖完成"
    ls -la /overlay/upper/etc/config/network
ENDSSH

if [ $? -ne 0 ]; then
    echo "失败！"
    exit 1
fi

# 3. 完成提示
echo ""
echo "全部完成！"
echo "================================"
echo "  已覆盖到 overlay："
echo "  - LAN IP: 10.0.0.1/24"
echo "  - WAN: DHCP 自动获取"
echo "  - mocktool + argon 已集成"
echo "================================"
echo ""
echo "请手动重启路由器使配置生效："
echo "  ssh root@'$ROUTER_IP' /sbin/init 6"
echo ""
echo "重启后访问: http://10.0.0.1"
