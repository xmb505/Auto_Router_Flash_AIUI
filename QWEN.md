# Auto Router Flash AIUI — 路由器刷机平台

小米 / Redmi / JGC 多型号路由器自动化刷机工具。

**方向：AI 驱动的后端引擎。** 不再有 TUI。AI（包括本助手、其他 LLM CLI 工具等）是主要操作者。所有脚本的输入输出优先为机器可解析设计，同时保持人类可读。

## 项目哲学

本项目遵循 **Unix 哲学**（详见 `doc/conventions/03-unix-philosophy.md`）：

- 每个脚本只做**一件事**（Rule of Modularity）
- 脚本间通过 stdin/stdout JSON 串联（Rule of Composition）
- 进度走 stderr，数据走 stdout（Rule of Silence + Transparency）
- 先做出能跑的原型，再优化（Rule of Optimization）
- 输出对 AI 友好 = 对所有人友好（AI-first 解读）

## 目录结构

```
Auto_Router_Flash_AIUI/
├── QWEN.md                 # 本文件 — 项目总上下文
│
├── doc/
│   └── conventions/        # 编码规范
│       ├── 00-coding-standards.md # 编程规范总纲（索引 + 速查）
│       ├── 01-naming.md           # 命名约定
│       ├── 02-script-contract.md  # 脚本契约（AI 友好 + 机器可解析）
│       ├── 03-unix-philosophy.md  # Unix 哲学总则（含 AI 语境解读）
│       ├── 04-utility-contract.md # 工具脚本契约
│       └── 05-ai-interface.md     # ★ AI 接口设计规范
│
├── src/
│   └── project/            # 按机型组织的步骤脚本
│       ├── cr660x/         # {doc/, files/, N.step.py...}
│       ├── jgc-qx/
│       ├── ax3000t/
│       ├── ax3600/
│       ├── ax5/
│       ├── ax6/
│       └── newifid2/       # Newifi D2（非小米，breed 刷机）
│
├── old_coding/             # 重构素材库（不再作为运行目标）
│   ├── Auto_Flash_Router/  # AX 系列原始工具
│   ├── code/               # CR660X / JGC 原始工具
│   ├── router-flash/       # 旧融合工具（含 TUI）
│   ├── AX5/
│   └── AX6/
│
└── old_code/               # 早期代码（参考用）
```

### old_coding/ 使用约定

- `old_coding/` 是**重构素材库**，不是墓园
- 写 `src/project/` 下新脚本时，从 `old_coding/` 对应文件**拆逻辑、抽常量、抽函数**
- 不原地修改 `old_coding/` 中的旧文件
- `old_coding/router-flash/TUI/` 层视为过时参考，不作为移植目标

## 支持型号

| 目录 | 型号 | SoC | 架构 | 状态 |
|------|------|-----|------|------|
| `ax3600` | 小米 AX3600 (R3600) | IPQ8071A | ARM | ✅ 完整流水线 |
| `ax6` | 红米 AX6 (RA69) | IPQ8071A | ARM | ✅ 完整流水线 |
| `cr660x` | 小米 CR660X (联通定制) | MT7621 | MIPS | ✅ 完整流水线 |
| `newifid2` | D-Team Newifi D2 | MT7621 | MIPS | 部分完成（breed_enter 实测通过） |
| `ax5` | 红米 AX5 (RA67) | IPQ6000 | ARM | 骨架（含通用 SSH 脚本） |
| `ax3000t` | 小米 AX3000T (RD03) | IPQ5000 | ARM | 骨架（含通用 SSH 脚本） |
| `jgc-qx` | JGC Qx | MT7621 | MIPS | 骨架（含通用 SSH 脚本） |

## 关键约定

### 脚本契约（新代码）

所有 `N.step.py` 遵守 `doc/conventions/02-script-contract.md`，核心规则：

| 规则 | 说明 |
|------|------|
| **stdout = 一个 JSON** | `{"ok":true,"data":{...}}` 或 `{"ok":false,"error":"...","recoverable":bool}` |
| **stderr = 进度/日志** | 仅 `--debug` 时输出，不写结果数据 |
| **exit code** | 0=成功, 1=通用, 2=参数, 3=网络, 4=认证, 5=超时 |
| **argparse + --help** | 每个脚本必须支持; `--help-json` 输出参数 JSON Schema |
| **标准开关** | `--debug`, `--timeout`, `--ip` |
| **无隐式依赖** | 优先标准库，三方库在 import 区声明 |

### AI 友好的输出

JSON 只表达执行结果和业务数据。流程编排和排错恢复走文档，不嵌入 JSON。

成功时输出业务数据，失败时输出错误分类（`reason`）和可恢复性（`recoverable`），AI 凭 `reason` 字段查 `doc/troubleshooting.md` 获取恢复步骤。

详见 `doc/conventions/05-ai-interface.md`。

### 命名约定

全部定义在 `doc/conventions/01-naming.md`，速查：

- **步骤脚本**: `<数字>.<动词短语>.py`
- **机型目录**: 小写 + 连字符
- **资源目录**: 小写复数 → `doc/`, `files/`
- **Python 标识符**: snake_case, 常量 UPPER_CASE
- **JSON 字段**: snake_case, 布尔 `is_` / `has_` 前缀

### 机型文档要求

每个机型 `doc/` 目录必须包含：

| 文件 | 内容 |
|------|------|
| `flash-pipeline.md` | 完整刷机流程（步骤顺序、决策分支、状态检查点） |
| `enable-ssh.md` | 开 SSH 的方法细节 | 
| `troubleshooting.md` | 常见错误列表（错误现象、原因、恢复命令） |
| `model-info.md` | 机型硬件信息（SoC、Flash 布局、MTD 表、加密模式） |

### 密码学共享常量

所有小米路由器共享相同的加密基础：

| 常量 | 值 |
|------|-----|
| `KEY` | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| `IV` | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |

## 入口迁移路径（远期规划，当前未实现）

```
规划: flash.sh → src/orchestrator.py (AI 友好的 CLI orchestrator)
```

> 当前 `flash.sh` 和 `src/orchestrator.py` 均未创建。未来将实现一个无状态 orchestrator，接收高层次目标（如 `--target openwrt`）后自动编排步骤流水线。近期方向是胶水脚本串联步骤。

## 开发流程

1. 阅读 `old_coding/` 下对应机型的原始脚本
2. 参考 `doc/conventions/` 全部规范
3. 在 `src/project/<机型>/` 下创建步骤脚本
4. 确保 `doc/troubleshooting.md` 覆盖已知错误
5. 每个脚本可独立运行测试：`python3 ./N.step.py`

## 注意事项

- **刷机有风险** — 每一步都必须先检测再执行，失败时大声报错（在 JSON 里）
- **AI 是操作者** — 错误信息必须让 AI 通过 `reason` 字段查文档定位恢复流程
- **文档不是摆设** — `troubleshooting.md` 是 AI 排错的知识库，`flash-pipeline.md` 是流程编排的依据，必须随脚本更新
- **不许闭门造车** — 没有实物在手时只搭目录和文档骨架，不写业务脚本/步骤脚本。刷机行为涉及真实网络交互和硬件协议，未经实物验证的代码不可信任
- **安全** — 不要硬编码密码 / stok 到代码中，走参数传递
- **非 pip 包** — `src/project/` 下不创建 `__init__.py`
- **stderr 可见性** — 刷机过程必须实时可见进度，但仅当 `--debug` 时
- **SSH host key** — 路由器只提供 `ssh-rsa` 旧算法，连接时需 `-oHostKeyAlgorithms=+ssh-rsa`
