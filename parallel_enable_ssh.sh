#!/bin/bash
# parallel_enable_ssh.sh — 并行 SSH 进 3 个 LXC 容器，同时开路由器 SSH
# 用法: ./parallel_enable_ssh.sh
# 依赖: sshpass (apk add sshpass / apt install sshpass)

set -e

CONTAINER_PWD="12345678"

# 容器IP → 路由器IP → 路由器密码
declare -A ROUTER_MAP
ROUTER_MAP["202:172.16.11.2"]="192.168.31.1 g9e3n7fk"
ROUTER_MAP["203:172.16.11.3"]="192.168.10.1 t3sxwmv4"
ROUTER_MAP["204:172.16.11.4"]="192.168.31.1 5Ryqqrp!"

run_one() {
  local container_ip="$1"
  local router_ip="$2"
  local router_pwd="$3"
  local logfile="/tmp/enable_ssh_${container_ip}.log"

  echo "[$(date +%H:%M:%S)] 开始: ${container_ip} → ${router_ip}" | tee -a "$logfile"

  sshpass -p "$CONTAINER_PWD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "root@${container_ip}" \
    "cd /root/cr660x && python3 2.login_get_stok.py --ip ${router_ip} --pwd ${router_pwd} 2>/dev/null | python3 3.enable_ssh.py --ip ${router_ip} 2>/dev/null" \
    2>&1 | tee -a "$logfile"

  echo "[$(date +%H:%M:%S)] 完成: ${container_ip} → ${router_ip}" | tee -a "$logfile"
}

echo "=== 并行开 SSH (202/203/204) ==="
echo ""

# 并行启动 3 个后台进程
for key in "${!ROUTER_MAP[@]}"; do
  container_ip="${key#*:}"
  vals="${ROUTER_MAP[$key]}"
  router_ip="${vals%% *}"
  router_pwd="${vals##* }"
  run_one "$container_ip" "$router_ip" "$router_pwd" &
done

# 等所有完成
wait
echo ""
echo "=== 全部完成 ==="
