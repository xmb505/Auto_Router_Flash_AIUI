# Router Flash Platform — 路由器批量刷机平台

统一融合工具，支持小米/Redmi 多型号路由器刷机、SSH 开启、Bootloader 刷写等。

## 快速启动

```bash
# 方式一：快捷入口
./flash.sh

# 方式二：直接运行
python3 flash.py

# 方式三：root 入口
bash /root/flash.sh
```

## 支持型号

| 序号 | 型号 | 说明 |
|------|------|------|
| 1 | CR660X | 小米/联通定制版，三阶段刷机 (TUI) |
| 2 | JGC Q10/Q20 | JGC 系列，三阶段刷机 (TUI) |
| 3 | AX3000T | 小米/Redmi AX3000T |
| 4 | AX3600 | 小米 AX3600 |
| 5 | AX5 | Redmi AX5 |
| 6 | AX6 | Redmi AX6 |
| 7 | xmir-patcher | 通用小米路由器补丁工具 |
| 8 | HTTP Server | 内置 chfs 文件服务器 |

## 目录结构

```
router-flash/
├── flash.py           # 统一入口菜单
├── main.py            # CR660X/JGC TUI 主程序
├── config.py          # 配置加载
├── config.yaml        # 配置文件
├── utils.py           # 公共工具函数
├── README.md          # 本文件
│
├── cr660x/            # CR660X 刷机模块 + 固件
├── jgc/               # JGC 刷机模块 + 固件
├── ax3000t/           # AX3000T 刷机脚本 + 固件
├── ax3600/            # AX3600 刷机脚本 + 固件
├── ax5/               # Redmi AX5 刷机脚本 + 固件
├── ax6/               # Redmi AX6 刷机脚本 + 固件
├── xmir-patcher/      # 通用小米路由器工具
├── httpserver/        # chfs HTTP 文件服务器
└── TUI/               # TUI 相关资源
```

## 依赖安装

CR660X/JGC TUI 界面需要：
```bash
pip3 install rich scapy requests
```

其他型号脚本多为独立 Python 脚本，一般无需额外依赖。

## 注意事项

- 刷机有风险，请确认路由器型号匹配
- 操作前建议备份原厂固件
- xmir-patcher 使用时请参考其内置文档
- HTTP 服务器用于路由器从本机下载固件

## 来源

本项目融合自：
- `code/` — CR660X / JGC 刷机工具 (TUI)
- `Auto_Flash_Router/` — AX 系列刷机工具 + xmir-patcher
