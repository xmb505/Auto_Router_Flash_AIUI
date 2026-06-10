# Auto Router Flash AIUI — 路由器刷机平台

小米 / Redmi / JGC 多型号路由器自动化刷机工具。正在从单体脚本重构为 Unix 哲学风格的小工具流水线。

## 项目哲学

本项目遵循 **Unix 哲学**（详见 `doc/conventions/03-unix-philosophy.md`）：

- 每个脚本只做**一件事**（Rule of Modularity）
- 脚本间通过 stdin/stdout JSON 串联（Rule of Composition）
- 进度走 stderr，数据走 stdout（Rule of Silence + Transparency）
- 先做出能跑的原型，再优化（Rule of Optimization）

## 目录结构

```
Auto_Router_Flash_AIUI/
├── QWEN.md                 # 本文件 — 项目总上下文
├── flash.sh                # 兼容入口 → old_coding/router-flash/main.py (Rich TUI)
├── paste.txt               # TUI 调试输出快照（临时保留）
│
├── doc/                    # 项目文档
│   └── conventions/        # 编码规范
│       ├── 01-naming.md          # 命名约定
│       ├── 02-script-contract.md # 脚本契约（stdout/stderr/exit code）
│       └── 03-unix-philosophy.md # Unix 哲学总则
│
├── src/                    # ★ 活跃工作区 — 重构中的新代码
│   └── project/            # 按机型组织的步骤脚本
│       ├── cr660x/         # {doc/, files/, N.step.py...}
│       ├── jgc-q10/
│       ├── jgc-qx/
│       ├── ax3000t/
│       ├── ax3600/
│       ├── ax5/
│       └── ax6/
│
├── old_coding/             # 旧代码仓库 — 重构素材库
│   ├── Auto_Flash_Router/  # AX 系列原始工具（含 crypto / SSH / TFTP / HTTP）
│   ├── code/               # CR660X / JGC 原始工具（含 TUI）
│   ├── router-flash/       # 融合工具（flash.py → main.py 统一入口）
│   ├── AX5/                # AX5 固件资源
│   └── AX6/                # AX6 固件资源
│
└── tmp/                    # 整理暂存 — 待手动清理
    ├── 整理报告.md
    ├── flash               # 旧 flash 脚本（与 flash.sh 重复）
    ├── AX5_sysupgrade-redmi_ax5/   # 固件解包产物
    └── AX6_libwrt-extracted/       # 固件解包产物
```

### old_coding/ 使用约定

- `old_coding/` 是**重构素材库**，不是墓园
- 写 `src/project/` 下新脚本时，从 `old_coding/` 对应文件**拆逻辑、抽常量、抽函数**
- 不原地修改 `old_coding/` 中的旧文件
- `flash.sh` 保留指向 `old_coding/router-flash/main.py`，维持兼容

## 支持型号

| 目录 | 型号 | SoC | 架构 |
|------|------|-----|------|
| `cr660x` | 小米 CR660X (联通定制) | MT7621 | MIPS |
| `jgc-q10` | JGC Q10 | MT7621 | MIPS |
| `jgc-qx` | JGC Qx | MT7621 | MIPS |
| `ax3000t` | 小米 AX3000T (RD03) | IPQ5000 | ARM |
| `ax3600` | 小米 AX3600 (R3600) | IPQ8071A | ARM |
| `ax5` | 红米 AX5 (RA67) | IPQ6000 | ARM |
| `ax6` | 红米 AX6 (RA69) | IPQ8071A | ARM |

> 机型目录使用小写 + 连字符命名（`jgc-q10`、`ax3000t`）

## 关键外部约定

### 脚本契约（新代码）

所有 `N.step.py` 遵守 `doc/conventions/02-script-contract.md`，核心规则：

| 规则 | 说明 |
|------|------|
| **stdout = 一个 JSON** | `{"ok":true,"data":...}` 或 `{"ok":false,"error":"..."}` |
| **stderr = 进度/日志** | 给人类看的，不写结果数据 |
| **exit code** | 0=成功, 1=通用错误, 2=参数错误, 3=网络, 4=认证, 5=超时 |
| **argparse + --help** | 每个脚本必须支持 |
| **标准开关** | `--debug`（默认关；开了才打进度到 stderr）, `--timeout`, `--router` |
| **无隐式依赖** | 优先标准库，三方库在 import 区声明 |

### 命名约定

全部定义在 `doc/conventions/01-naming.md`，速查：

- **步骤脚本**: `<数字>.<动词短语>.py` → `1.check_miwifiapi.py`, `2.auto_init.py`
- **机型目录**: 小写 + 连字符 → `jgc-q10/`, `ax3000t/`
- **资源目录**: 小写复数 → `doc/`, `files/`
- **Python 标识符**: snake_case, 常量 UPPER_CASE, 类 PascalCase
- **JSON 字段**: snake_case, 布尔 `is_` / `has_` 前缀

### 脚本输入来源优先级

1. 网络自动探测（无状态，首选）
2. 命令行参数（确定性）
3. stdin JSON（链式调用）

## 密码学共享常量

所有小米路由器共享相同的加密基础：

| 常量 | 值 |
|------|-----|
| `KEY` | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| `IV` | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |

两种加密模式：

| | `newEncryptMode=1` (AX3000T) | `newEncryptMode=0` (AX5/AX3600/...) |
|---|---|---|
| 登录哈希 | SHA256(nonce + SHA256(pwd+KEY)) | SHA1(nonce + SHA1(pwd+KEY)) |
| 注入 API | `start_binding` (key 参数) | `set_config_iotdev` (ssid 参数) |
| 分隔符 | `\n` | `;` |

## 工作流程

### 新机型适配

对于每个机型，在 `src/project/<机型>/` 下按逻辑顺序创建步骤脚本：

```
src/project/ax3000t/
├── 1.check_miwifiapi.py     # 检测路由器 API 状态 → JSON
├── 2.auto_init.py           # 自动化初始化向导 → JSON
├── 3.downgrade.py           # 降级固件
├── 4.enable_ssh.py          # 命令注入开 SSH
├── 5.flash_uboot.py         # 刷写自定义 uboot
├── 6.tftp_serve.py          # TFTP 服务（如需要）
├── doc/                     # 该机型文档
└── files/                   # 固件 / 补丁 / 脚本资源
```

### 开发流程

1. 阅读 `old_coding/Auto_Flash_Router/<机型>/` 下原始脚本
2. 参考 `doc/conventions/` 三份规范
3. 在 `src/project/<机型>/` 下按步骤编号创建脚本
4. 每个脚本从 `1` 开始编号，确保独立可运行
5. 写完一步可以用 `python3 ./N.step.py` 单独测试

## 兼容入口

```bash
# 启动旧 Rich TUI（old_coding/router-flash/main.py）
./flash.sh

# 等新 src/project/ 重构完毕后，入口会切换
```

## 注意事项

- **刷机有风险** — 每一步都必须先检测再执行，失败时大声报错
- **安全** — 不要硬编码密码 / stok 到代码中，走参数传递
- **非 pip 包** — `src/project/` 下不创建 `__init__.py`，不是可安装 Python 包
- **stderr 可见性** — 刷机过程必须实时可见进度，禁止 stdout 吞噬所有输出
- **SSH host key** — 路由器只提供 `ssh-rsa` 旧算法，连接时需 `-oHostKeyAlgorithms=+ssh-rsa`
