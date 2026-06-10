#!/bin/bash
# 通过 uboot web UI 上传固件
# 用法: ./uboot_upload.sh <固件文件>

FW="${1}"
IP="192.168.1.1"

if [ -z "$FW" ] || [ ! -f "$FW" ]; then
    echo "用法: $0 <固件文件>"
    echo ""
    echo "固件格式要求:"
    echo "  请根据 uboot_mod 确认支持的格式（FIT .itb 或原始 UBI 镜像）"
    exit 1
fi

echo "=== 通过 uboot web UI 上传固件 ==="
echo "  文件: $FW ($(du -h "$FW" | cut -f1))"
echo "  目标: http://$IP/"

# 使用 curl 模拟浏览器上传
curl -# -F "firmware=@$FW" "http://$IP/"

echo ""
echo "上传完成，uboot 正在刷写固件，请勿断电"
