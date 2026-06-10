---
name: step-script-default-silent-debug
description: 路由器刷机步骤脚本（src/project/<机型>/N.step.py）的日志约定 —— 默认静默，--debug 显式开启 stderr 日志；不写 --quiet/--verbose
source: auto-skill
extracted_at: '2026-06-08T16:01:14.518Z'
---

# 步骤脚本 —— 默认静默 / `--debug` opt-in

## 适用场景

写 `src/project/<机型>/N.step.py` 这类 Unix 风格的步骤脚本，遵循项目脚本契约（stdout=JSON, stderr=人类日志, exit=状态码），但需要决定"日志该怎么输出"时使用。

## 硬约束（用户口径）

> "言多必失，这会导致管道流难以处理"

**默认静默**。成功路径下：
- stdout 恰好一个 JSON
- stderr 什么也不写
- exit code = 0

调用方想看过程 → 显式传 `--debug`。

## 反例（不要这样做）

- ❌ 给脚本加 `--quiet` / `--verbose` 两个开关（配置复杂、违反 Rule of Silence）
- ❌ 默认就打印 `[INFO] ...` 时间戳日志（污染管道，干扰下游 `| jq`）
- ❌ 把 `quiet` 参数一层层透传到 `log(msg, quiet=...)` 形参上
- ❌ 用 `logging` 模块的默认 INFO 级别（同样会污染 stdout）
- ❌ 失败时把 traceback 打到 stdout（破坏 JSON 单输出约束）

## 代码模板（每个步骤脚本照抄）

```python
# 顶部常量区
DEBUG = False  # 运行时由 --debug 改写；默认静默

# 日志函数
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)

# argparse —— 只加 --debug
p.add_argument("--debug", action="store_true",
               help="打印进度日志到 stderr（默认静默，仅输出 JSON）")

# main() —— 改写模块全局
def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug
    ...
    # 业务函数签名不再带 quiet / debug 参数
    data = business_fn(args.router, ...)
```

## 关键决策

| 决策 | 原因 |
|------|------|
| 模块级 `DEBUG` 全局 | 函数签名干净（不污染业务函数），改写点在 `main()` 集中 |
| 只有 `--debug`，没有 `--quiet` | 默认就是 quiet，再加 `--quiet` 是冗余配置；用户的反馈是"去掉 verbose" |
| stderr 而非 stdout | 仍然区分"数据流"和"日志流"，但默认关掉日志源 |
| 失败也走 `ok:false` JSON | 失败用 stdout JSON 表达（机器可读），stderr 静默，错误详情在 JSON 的 `error` 字段里 |

## 同步要改的地方

新增/修改任何一个步骤脚本时，**同时**检查以下三项保持一致：

1. `doc/conventions/02-script-contract.md` —— 标准开关段已写"默认静默 / `--debug`"，引为权威
2. `doc/conventions/03-unix-philosophy.md` —— Rule of Silence 段是哲学根因
3. 该机型的 `doc/README.md` —— 调用示例里不要出现 `--quiet`，调试示例用 `--debug`

## 已落地的例子

`src/project/ax6/1.official_init.py` 是当前唯一完整范本：
- `DEBUG` 模块全局 + `log()` 单参签名
- argparse `--debug` action="store_true"
- `main()` 改写全局后调 `official_init(... 无 quiet 参数)`
- 业务函数 `official_init(router_ip, ssid, wifi_pwd, admin_pwd, timeout)` 干净

## 验收

- `python3 N.step.py` → 只有一行 JSON，stderr 全空
- `python3 N.step.py --debug` → stderr 出 `[INFO] ...` 进度，stdout 仍是 JSON
- `python3 N.step.py --help` → 列出 `--debug` 选项
- 失败时（如路由器不可达）→ stdout 仍是单个 `{"ok":false,"error":"..."}`，stderr 全空
