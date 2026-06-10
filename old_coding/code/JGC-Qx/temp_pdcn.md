### 13. pdcn_flash_all.py

此脚本用于自动化执行完整的PDCN系统bootloader刷入流程，整合了所有PDCN相关的刷机步骤。

#### 功能
- 自动检测路由器是否在线 (默认IP: 192.168.123.1)
- 自动上传bootloader到路由器
- 自动刷入bootloader到Bootloader分区
- 自动重启路由器
- 循环执行，适合批量刷机操作

#### 使用方法
```bash
# 直接运行脚本
python3 pdcn_flash_all.py
```

#### 刷机流程
1. 检测路由器是否在线 (ping 192.168.123.1)
2. 上传bootloader到路由器 (/tmp/pb-boot.img)
3. 刷入bootloader到Bootloader分区
4. 重启路由器
5. 等待10秒后开始下一轮刷机流程

#### 特殊处理
- 循环执行，适合批量刷机操作
- 自动处理路由器不在线的情况，提示用户检查连接
- 提供详细的进度提示和错误信息
- 每轮刷机完成后自动等待10秒再开始下一轮