#!/bin/bash
# 路由器刷机平台 - 快速入口（直接启动 Rich TUI）
# Router Flash AIUI Platform - Quick Entry
# 注: router-flash/ 已归档至 old_coding/，本脚本保留指向旧路径以维持兼容

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM_DIR="$SCRIPT_DIR/old_coding/router-flash"

cd "$PLATFORM_DIR" || {
    echo "错误: 找不到 $PLATFORM_DIR 目录"
    exit 1
}

python3 main.py
