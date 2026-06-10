#!/bin/bash
# 4.firmware_upload_on_miwifi.sh — 上传文件到 AX6 路由器 /tmp
# 省掉 ssh-rsa 警告 + 加 -O 绕过 sftp（旧 Dropbear 不支持）
# 完成后输出 JSON（成功 ok=true / 失败 ok=false，免看退出码）
# 默认：透传 scp stderr（看得到进度条），但过滤 "Warning: Permanently added"
# --debug：保留所有 stderr（包括 warning）
#
# 用法: ./4.firmware_upload_on_miwifi.sh --file <本地文件> [选项]
# 必传: --file <本地文件>
# 可选: --ip <IP>              默认 192.168.31.1
#       --target-name <name>   默认 <file> 的 basename
#       --ssh-pwd <密码>        默认 root
#       --debug                保留所有 stderr（host key warning 等）
#       -h | --help             显示本帮助
#
# 依赖: sshpass  (apt install sshpass / apk add sshpass)

ip="192.168.31.1"
ssh_pwd="root"
file=""
target=""
debug=0

while [ $# -gt 0 ]; do
  case "$1" in
    --file)        file="${2:-}"; shift 2 ;;
    --ip)          ip="${2:-}"; shift 2 ;;
    --target-name) target="${2:-}"; shift 2 ;;
    --ssh-pwd)     ssh_pwd="${2:-}"; shift 2 ;;
    --debug)       debug=1; shift ;;
    -h|--help)     sed -n '2,15p' "$0"; exit 0 ;;
    *)             printf '{"ok": false, "error": "未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

if [ -z "$file" ]; then
  echo '{"ok": false, "error": "--file 必传"}'
  exit 2
fi
if [ ! -f "$file" ]; then
  printf '{"ok": false, "error": "文件不存在: %s"}\n' "$file"
  exit 2
fi
[ -z "$target" ] && target=$(basename "$file")

if [ "$debug" = 1 ]; then
  sshpass -p "$ssh_pwd" scp -O \
    -oHostKeyAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no \
    -oUserKnownHostsFile=/dev/null \
    "$file" "root@${ip}:/tmp/${target}"
  rc=$?
else
  sshpass -p "$ssh_pwd" scp -O \
    -oHostKeyAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no \
    -oUserKnownHostsFile=/dev/null \
    "$file" "root@${ip}:/tmp/${target}" \
    2> >(sed -u '/^Warning: Permanently added/d' >&2)
  rc=$?
fi

if [ "$rc" = 0 ]; then
  printf '{"ok": true, "file": "%s", "target": "/tmp/%s", "ip": "%s"}\n' \
    "$file" "$target" "$ip"
  exit 0
fi

printf '{"ok": false, "error": "scp 失败 (exit %d)", "file": "%s", "ip": "%s"}\n' \
  "$rc" "$file" "$ip"
exit "$rc"
