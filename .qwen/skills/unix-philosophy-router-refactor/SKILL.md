---
name: unix-philosophy-router-refactor
description: 把路由器刷机工具用「Unix 哲学 + 数字前缀脚本」模式重构的完整骨架（项目布局、命名约定、文档规范、旧物归档、入口兼容）
source: auto-skill
extracted_at: '2026-06-08T04:02:13.519Z'
---

# Unix 哲学 × 路由器刷机工具 — 重构骨架

## 适用场景

用户表达出以下意图中的多个：
- "用 Unix 哲学重构"、"小工具组合"、"管道风格"
- "每个步骤拆成独立脚本"、"数字前缀命名"
- "模块化"、"慢慢来"、"先建骨架"
- 涉及小米 / 红米 / CR660X / JGC / AX 系列等路由器刷机工具

## 不要做的（反例先行）

- ❌ **不要建 Python 包结构**（`src/<package>/__init__.py` + `pyproject.toml`）——这是"重型重构"思路，本模式是"工程内工作目录"
- ❌ **不要问要不要建** `__init__.py` —— 答案永远是"不要"。脚本靠 `sys.path` / 相对路径引用，不靠 import
- ❌ **不要建 `core/` `backends/` `tools/` `tui/`** 之类的多子目录骨架 —— 用户没要求分层的复杂度，先保持平面
- ❌ **不要在 src/ 下建空骨架后立刻填内容** —— 用户说"慢慢来"就先停手，等下一个具体任务
- ❌ **不要把旧物丢到 `tmp/`** —— 旧代码是"重构素材库"，不是"待删品"

## 目录布局

```
<项目根>/
├── src/                          # 新工作区根
│   └── project/                  # 项目工作目录（不带 __init__.py）
│       ├── cr660x/    {doc/, files/}
│       ├── jgc-q10/   {doc/, files/}
│       ├── jgc-qx/    {doc/, files/}
│       ├── ax3000t/   {doc/, files/}
│       ├── ax3600/    {doc/, files/}
│       ├── ax5/       {doc/, files/}
│       └── ax6/       {doc/, files/}
│
├── doc/                          # 项目文档
│   └── conventions/              # 规范（按数字前缀 + 主题分文件）
│       ├── 01-naming.md          # 命名约定
│       ├── 02-script-contract.md # 脚本契约（含 AI 友好输出）
│       ├── 03-unix-philosophy.md # Unix 哲学总则
│       ├── 04-utility-contract.md# 工具脚本契约
│       └── 05-ai-interface.md   # AI 接口设计规范（--help-json / reason 分类 / troubleshooting 集成）
│
├── old_coding/                   # 旧物容器（重构素材库）
│   ├── Auto_Flash_Router/        # 旧仓库 1
│   ├── code/                     # 旧仓库 2
│   ├── router-flash/             # 融合产物（已迁出的项目）
│   ├── AX5/                      # 顶层型号资源
│   └── AX6/
│
├── flash.sh                      # 入口脚本（改指向 old_coding/...）
├── tmp/                          # 临时整理产物（含整理报告）
└── .qwen/                        # 项目记忆 + skills
```

## 命名约定

| 类别 | 规则 | 示例 |
|------|------|------|
| 机型目录 | 小写 + 连字符 | `cr660x/`, `jgc-q10/`, `ax3000t/` |
| 步骤脚本 | `<数字>.<动词短语>.py` | `1.check_miwifiapi.py`, `2.auto_init.py` |
| 资源子目录 | 小写，复数 | `doc/`, `files/` |
| 规范文档 | `<数字>-<主题>.md` | `01-naming.md` |

数字前缀的关键决策：
- 一律从 `1` 起，递增
- 数字反映**逻辑顺序**，不是"调用次数"
- 数字可跳：缺号表示该步有可选项
- 数字不代表依赖关系（脚本自身可独立运行）

## 脚本契约（每个步骤脚本必遵循）

| 通道 | 用途 | 格式 |
|------|------|------|
| **stdout** | 机器可读结果 | 单一 JSON 对象 |
| **stderr** | 人类可读进度 | 自由文本 |
| **exit code** | 成功/失败 | `0` 成功 / 非 `0` 失败 |

- 必须支持 `--help`（argparse），**必须支持 `--help-json`**（参数 JSON Schema，供 AI 自动构造命令行）
- 成功 JSON：`{"ok": true, "step": "...", "data": {...}}`
- 失败 JSON：`{"ok": false, "step": "...", "error": "...", "reason": "stok_expired", "recoverable": true}`  
  — `reason` 是标准化错误分类，AI 凭此查 `troubleshooting.md`；`recoverable` 告诉 AI 能否自动重试
- **JSON 不做导航**：`next_steps`/`recovery` 不放 JSON 里，流程编排走 `flash-pipeline.md`，排错走 `troubleshooting.md`
- 优先网络自动探测，次选 CLI 参数，末选 stdin JSON
- 临时文件用 `tempfile.NamedTemporaryFile`，不污染当前目录
- 三方依赖在文件顶部 `import` 区集中声明
- 每个机型 `doc/` 目录必须有 `flash-pipeline.md`（流程）、`troubleshooting.md`（排错）、`model-info.md`（硬件参数）

## 工作流（用户说"开始"时按顺序）

1. **建项目根 `src/project/`**（注意是 `project` 不是 `router_flash` 之类的包名）
2. **建机型子目录**（cr660x、jgc-q10、jgc-qx、ax3000t、ax3600、ax5、ax6），每个下 `doc/` 和 `files/`
3. **建 `doc/conventions/` 写规范**：先 3 份（命名、契约、哲学），后续按需扩充
4. **建 `old_coding/` 收旧物**：
   - 旧仓库（`code/`、`Auto_Flash_Router/`）
   - 融合产物（`router-flash/`）
   - 顶层型号资源（`AX5/`、`AX6/`）—— 视用户决定
5. **修入口脚本兼容**（如 `flash.sh`）：把 `PLATFORM_DIR="$SCRIPT_DIR/router-flash"` 改成 `$SCRIPT_DIR/old_coding/router-flash`，加注释说明已归档
6. **后续**：从 `old_coding/` 抽逻辑进 `src/project/<机型>/<数字>.<step>.py`

## 何时该问、什么时候该停

- ✅ **问**：哪些目录要搬入 `old_coding/`（用户决定性偏好）
- ✅ **问**：机型目录是否齐全（用户可能漏了 `jgc-q20` 等变体）
- ❌ **不问**：要不要 `__init__.py`（默认不要）
- ❌ **不问**：要不要建 `core/` `tools/` 等子层（默认不建）
- ❌ **不问**：脚本契约细则（直接按 doc/ 里的写）

## 关键决策的"为什么"

| 决策 | 原因 |
|------|------|
| `src/project/` 而非 `src/router_flash/` | 避免 pip 包印象，凸显"工程内工作目录"性质 |
| 不要 `__init__.py` | 不是发布包，只是文件容器 |
| 连字符机型目录 | 跨 shell/工具友好，与已有 `router-flash/ax3000t/` 等保持一致 |
| `old_coding/` 而非 `tmp/` 或 `legacy/` | 旧代码要被反复抽逻辑，是"重构素材库"而非"垃圾场" |
| 数字前缀而不是 `01_check_*` | `1.xxx.py` 在 shell 里直接 `python3 ./1.xxx.py` 跑，简单可读 |
| 文档先行（3 份规范） | 规范先于代码，避免边写边反复改约定 |

## 状态机（用户意图识别）

```
用户说                        →  你做什么
─────────────────────────────────────────────────
"模块化/重构/Unix 哲学"        →  问：建哪/范围多大？默认推荐本 skill
"创建 src/..."                →  先建 `src/project/`，不建子目录
"建 <子目录>"                  →  按命名约定建
"清理/整理根目录"              →  见 router-flash-merge-cleanup
"开始重构/动手写脚本"          →  启动工作流第 1-5 步
"我有个具体脚本要写"           →  跳到工作流第 6 步，从 old_coding/ 抽
```
