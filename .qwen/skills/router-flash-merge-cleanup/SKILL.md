---
name: router-flash-merge-cleanup
description: 整理 Auto_Router_Flash_AIUI / router-flash 这类「融合型刷机工具项目」时的目录判定流程（识别融合源、解包产物、冗余入口）
source: auto-skill
extracted_at: '2026-06-08T02:36:40.234Z'
---

# router-flash 融合型刷机项目 — 整理判定

## 适用场景

项目根同时出现以下信号中的多个时使用：
- `router-flash/`、`merged/`、`platform/` 等"平台/融合"目录
- 与之并列的 `code/`、`Auto_Flash_Router/`、`legacy/` 等看起来"也是源码"的目录
- 顶层 `AX5/`、`AX6/`、`AX3000T/` 这类带**型号名**的目录，里面混杂 `*.bin` / `*.ubi` 主固件 + 嵌套的解包目录
- 根目录有 `flash` 和 `flash.sh` 同名内容脚本

## 判定流程

### 1. 先看融合项目的 README，确认"源 → 融合"关系
打开 `router-flash/README.md`（或同类入口），找形如：
> 本项目融合自 `code/` 和 `Auto_Flash_Router/`

**含义**：`code/`、`Auto_Flash_Router/` 是已被吸收的源仓库，**清不清由用户决定**，但不能默认就是垃圾。

### 2. 顶层带型号的目录（AX5/AX6/AX3000T/...）按"主固件 vs 解包产物"二分
进入该目录后，**第一层文件**通常是主固件（保留），**嵌套的解包目录**通常是临时产物（移到 tmp）：

| 文件/目录 | 处理 |
|-----------|------|
| `*.bin`、`*.ubi`、`*.tar.gz` | 保留（主固件/资源包） |
| `*-extracted/`、`sysupgrade-*/`、`libwrt-extracted/` | 移到 tmp |
| `overlay/`、`overlay-backup.tar.gz` | 视情况保留（用户可能还在用） |
| `mocktool-overlay/`、`mocktool-overlay.tar.gz` | 视情况保留 |

判定技巧：目录名带 `extracted`、`unsquashfs`、`ubireader` 痕迹，或包含 `CONTROL` + `kernel` + `root` 三件套（这是 sysupgrade.bin 的标准解包输出），即可判定为解包产物。

### 3. 根目录重复入口脚本
项目根同时存在 `flash` 和 `flash.sh`：
- `diff` 一下内容，完全相同就只保留 `.sh` 版本
- 注意**入口指向**：脚本里的 `python3 main.py` 未必和 README 写的 `python3 flash.py` 一致，最后在报告里提示一下这个不一致

### 4. 关于"xmir 暂时不动"（用户偏好类信号）
如果用户明确说"xmir 暂时不动"，那 `xmir-patcher/venv/`、`xmir-patcher/.git/`、`xmir-patcher/__pycache__/` 都**不要动**——用户可能在调试工具链。
对应命令：不要在清理脚本里加 `-name venv -prune`、`-name .git -prune` 这类过滤。

### 5. 整理报告必含项
- 移动的每一项 + 原始路径 + 释放空间
- 用户**显式决定保留**的项（避免后续被误清）
- "⚠️ 待处理"区列出**没动但用户可能想清的**候选（如 venv、__pycache__、.git）
- 报告本身写到 `tmp/整理报告.md`，与被清产物放一起

## 反例（不要这样做）

- ❌ 默认把 `code/` 和 `Auto_Flash_Router/` 丢到 tmp — README 已说"融合"，但用户可能仍要参考，必须先问
- ❌ 看到大文件就清 — 顶层 `AX5/*.bin` `AX6/*.ubi` 是主固件，不能跟 `extracted/` 一起丢
- ❌ 删除 `__pycache__` / `.git` / `venv` 而不问 — 这些对调试中的 xmir 工具链很重要
- ❌ 改写 `flash.sh` 的入口指向 — 这是改 bug 范围的事，整理只动结构、不修脚本语义
