---
name: step-script-migrate-from-old
description: 把 old_coding/ 下某个老脚本剥壳成 src/project/<机型>/N.step.py 的完整迁移流程（剥逻辑、扒常量、套约定、加校验）
source: auto-skill
extracted_at: '2026-06-08T16:15:00.290Z'
---

# 老脚本 → 新步骤脚本 — 迁移流程

## 适用场景

按 `unix-philosophy-router-refactor` 完成项目骨架后，进入"逐个迁移老脚本"阶段时使用。每次任务形式：

> "从 `old_coding/<repo>/<机型>/<X>.py` 剥出 <功能>，变成 `src/project/<机型>/<N>.<step>.py`"

## 前置

- 已读过 `doc/conventions/02-script-contract.md`（脚本契约 — 含 AI 友好输出）
- 已读过 `doc/conventions/05-ai-interface.md`（AI 接口设计规范）
- 已读过 `doc/conventions/01-naming.md`（命名约定）
- 已知道 `step-script-default-silent-debug` skill（`--debug` 模式 + 模块 `DEBUG` 全局）
- 已知道"啥都从路由器拿"哲学（KEY/IV/SSID/固件版本一律运行时探测）
- 已知道 **JSON 不做导航**：`next_steps` / `recovery` 不放进输出，流程编排走 `flash-pipeline.md`，排错走 `troubleshooting.md`

## 迁移流程（5 步）

### 1. 读老脚本，列"硬编码常量"清单

打开 `old_coding/Auto_Flash_Router/<机型>/<X>.py` 和 `old_coding/router-flash/<机型>/<X>.py`（**两份都看**，融合版可能比原始版更成熟）。

**重点扫描**（按优先级）：

| 硬编码类型 | 出现位置 | 替换方案 |
|----------|---------|---------|
| `KEY = "a2ff..."` / `IV = "6417..."` | 模块顶部 | 运行时扒 `init.html` 引用的 `init.<hash>.js` |
| `FACTORY_PWD = "admin"` | 模块顶部 | 仍是字面量"admin"——这是出厂约定，可以保留（**例外**） |
| 默认 IP `192.168.31.1` / `192.168.1.1` | argparse / 函数默认 | 保留为 `DEFAULT_ROUTER_IP` 常量（DHCP 网关约定） |
| `newEncryptMode = 0/1` 假设 | 加密逻辑 | JS 里 `\bnewEncryptMode\s*[:=]\s*(\d+)` 探测 |
| 加密算法（SHA1 vs SHA256）| `calc_*` 函数 | 按 `mode` 分支 |
| `--quiet` / `--verbose` flag | argparse | 删除，换 `--debug` |

**判定哪些常量可以"硬"**：
- ✅ 出厂约定（默认 IP、admin 密码、HTTP 路径）→ 保留为字面量
- ❌ 密码学密钥 → 必须运行时探测
- ❌ 业务数据（用户密码、stok、nonce）→ 永远参数化

### 2. 剥"扒 JS 自举"逻辑（如适用）

如果原脚本用 `KEY` 加密（几乎所有小米脚本都涉及），新脚本必须先扒 JS：

```python
def fetch_crypto_constants(ip, timeout) -> tuple[str, int]:
    """返回 (key, new_encrypt_mode)。"""
    html = http_get_raw(f"http://{ip}/init.html", timeout)
    m = re.search(r'/static/js/(init\.[a-f0-9]+\.js)', html)
    if not m:
        raise RuntimeError("未在 init.html 找到 init.*.js 引用")
    js = http_get_raw(f"http://{ip}/static/js/{m.group(1)}", timeout)
    key_m = re.search(r'\bkey\s*:\s*"([0-9a-f]{32})"', js)
    mode_m = re.search(r'\bnewEncryptMode\s*[:=]\s*(\d+)', js)
    if not key_m:
        raise RuntimeError("JS 里未找到 key 字段")
    mode = int(mode_m.group(1)) if mode_m else 0
    return key_m.group(1), mode
```

> **不要在自举函数里要求 IV**——除非原业务确实需要（如 `set_router_normal` 算 newPwd）。登录类脚本只需 KEY。

### 3. 套新约定

按 `step-script-default-silent-debug` skill 的模板：

```python
# 顶部
DEBUG = False  # 运行时由 --debug 改写；默认静默
STEP_NAME = "<step_name_in_snake_case>"

def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)

def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data}, ensure_ascii=False))

def emit_err(error: str, reason: str = "unknown", recoverable: bool = False) -> None:
    """失败输出。reason 见错误分类表，recoverable 告诉 AI 能否自动重试。"""
    print(json.dumps({
        "ok": False,
        "step": STEP_NAME,
        "error": error,
        "reason": reason,
        "recoverable": recoverable,
    }, ensure_ascii=False))

# argparse —— 严格遵循用户给的参数清单
# 默认静默 + --debug 唯一 opt-in
# 业务常用值给字面量默认（dev shortcut），不强制 required
p.add_argument("--debug", action="store_true", help="...")

# --help-json 支持（在 main() 开头处理）
if hasattr(args, 'help_json') and args.help_json:
    print_help_json(parser, STEP_NAME)
    return 0

# main()
def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug
    try:
        data = business_fn(...)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e), reason="unknown", recoverable=False)
        return 1
    emit_ok(data)
    return 0
```

**业务函数签名**：不带 `quiet` / `debug` 参数——日志门控由模块全局 `DEBUG` 决定，不污染业务逻辑。

**--help-json 实现**（在 parse_args 中加）：

```python
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="...")
    p.add_argument("--help-json", action="store_true",
                   help="输出参数 JSON Schema（供 AI 自动构造命令行）")
    # ... 其他参数
    return p.parse_args()

def print_help_json(parser: argparse.ArgumentParser, script_name: str) -> None:
    """输出 --help-json 格式。"""
    import inspect
    args_list = []
    for action in parser._actions:
        if action.option_strings:
            name = action.option_strings[0]
            is_flag = action.nargs == 0
            args_list.append({
                "name": name,
                "type": "flag" if is_flag else "string",
                "default": action.default if action.default is not None else None,
                "required": action.required,
                "description": action.help or "",
            })
    print(json.dumps({
        "script": script_name,
        "args": args_list,
    }, ensure_ascii=False))
```

### 4. 加状态校验（按需）

按脚本职责决定要校验什么。常用前置校验：

| 校验 | 适用脚本 | 实现 |
|------|---------|------|
| 路由器已初始化 | `login_get_stok`、`downgrade`、`enable_ssh` | `init_info.init=1, inited=0` → 拒绝 |
| 固件版本符合 | `downgrade`、需要 `bw160` 的 `set_router_normal` | 解析 `romversion` 字符串 |
| 端口可达 | 所有 HTTP 脚本 | 走 `urllib.request.urlopen` 自然抛错 |

**示例（已初始化校验）**：

```python
info = http_get_json(f"{base_url}/cgi-bin/luci/api/xqsystem/init_info", timeout)
is_factory = bool(info.get("init", 0)) and not info.get("inited", 0)
if is_factory:
    raise RuntimeError("路由器出厂未初始化，请先运行 1.official_init.py")
```

> 字段极性 `init`/`inited` 见 memory `project_xiaomi_inited_field_polarity.md`：`init=1`=需要 init，`inited=1`=已 init。

### 4b. 判定"方向性条件标志"——保留、去掉、还是统一传？

老脚本有些特征只在"特定方向"才触发（如降级才传 `downgrade=1`，首次运行才传 `init=1`）。
新脚本需要判断：这个方向性条件该保留，还是统一传？

**评估标准**：

| 标志类型 | 判断标准 | 处理 | 例子 |
|---------|---------|------|------|
| **绕过性标志**（bypass guard）| 去掉这条"避障"不影响正常方向的行为 | **永远传**，让调用方决定方向 | `syslock?downgrade=1`：是"跳过版本检查"的绕行标志，加了也不影响升新版。新脚本永远传。|
| **语义性标志**（changes behavior）| 去掉它，另一方向的行为就错了 | **保留为参数** | `flash_rom?custom=1`：不传就不能刷非官方固件。这是语义差异，不能永远传。 |
| **会话性标志**（changes auth scope）| 不同方向使用不同的会话权限 | **分开两个端点或两步处理** | `login?init=1` vs `login?init=0`：一个专用于工厂初始化会话，一个用于普通登录。路由器 API 本身拒绝反方向。不能统一。|

**决策口诀**：让脚本"不知道方向"——把方向决策留给调用方（用户或上游驱动），脚本只管"无脑刷"。这意味着绕过性标志统统去掉条件判断，统一硬编码。

> **实机验证**（AX6 √ 4.official_upgrade.py, 2026-06-08）：`downgrade=1` 统一传后，1.1.10→1.1.3（升级）和 1.1.3→1.0.16（降级）双向都正常工作。

### 4c. stok 从 CLI 还是管道来？（双向输入模式）

步骤脚本经常需要上游的 stok。**新脚本支持双向输入**——`--stok` 参数兜底，管道 stdin 主用：

```python
# argparse
p.add_argument("--stok", default="",
               help="stok（空则从 stdin 读上游 JSON）")

# main() 里先解决 stok
def read_stok_from_stdin() -> str:
    if sys.stdin.isatty():
        raise RuntimeError("未通过 stdin 管道传入上游 JSON，也未传 --stok")
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("stdin 为空")
    ...
    stok = d.get("data", {}).get("stok", "")
    if not stok:
        raise RuntimeError(f"上游 JSON 没有 data.stok 字段: {d}")
    return stok

def main() -> int:
    ...
    try:
        stok = args.stok or read_stok_from_stdin()
    except RuntimeError as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    ...
```

> **设计依据**：Unix 哲学的管道组合。`python3 2.login_get_stok.py | python3 3.enable_ssh.py` 就是 `stdout→stdin` 的经典链式调用范式。`--stok` 是独立调试时的便捷兜底。错误路径会**透传**上游的 `ok:false.error` 消息，而不是模糊地报"缺 stok"。

### 5. 验证（必做，不连机也能做）

```bash
# 语法
python3 -c "import ast; ast.parse(open('N.step.py').read())"

# argparse 跑通
python3 N.step.py --help

# 默认输出真的只有 JSON（连不上的 IP 会立刻抛错，仍是单个 ok:false JSON）
python3 N.step.py 2>&1 | head -1
```

## 决策清单

| 老脚本特征 | 新脚本做法 |
|----------|----------|
| 硬编码 `KEY` | 运行时扒 JS |
| 硬编码 `IV`（仅 newPwd 需要）| 同上（仅需要的脚本扒 IV） |
| 硬编码 `newEncryptMode` | JS 探测 + 分支 |
| `--quiet` / `--verbose` | 删，换 `--debug` |
| `print` 在 stdout 打进度 | 改 `log()` 走 stderr |
| 用 `requests` 库 | 改 `urllib.request`（除非已声明依赖） |
| 业务函数带 `quiet` 参数 | 删，改模块全局 `DEBUG` |
| 失败时 `print` 错误 + `sys.exit(1)` | `emit_err()` + `return 1` |
| 成功时 `print(json.dumps(...))` | `emit_ok({...})` |
| 入口需要交互输入密码 | **2026-06-08 之后**：直接 `required=True`，不传 default；用户必须显式知道自己的密码 |

## 落地参考

`src/project/ax6/2.login_get_stok.py` 是当前最完整的范本：

- ✅ 运行时扒 KEY（不写死）
- ✅ 自动探测 `newEncryptMode`（SHA1 / SHA256 分支）
- ✅ `--debug` 模块全局门控
- ✅ 单一 JSON stdout
- ✅ 前置校验"已初始化"
- ✅ `--pwd required=True`（不传魔数 default，强制显式传——哲学："啥都从路由器拿"）
- ✅ 业务函数 `login_get_stok(router_ip, admin_pwd, timeout)` 干净无 quiet 参数

## 反例（不要做）

- ❌ **直接复制老脚本** —— 老脚本违反 N 条新约定，逐条要剥
- ❌ **保留 `--quiet` `--verbose`** —— 冗余，违反 Rule of Silence
- ❌ **把 KEY 留在脚本顶部"作为兜底"** —— 哲学禁止 fallback 兜底，要就扒到，扒不到就报错
- ❌ **业务函数签名带 `debug` 参数** —— 用模块全局，门控集中在一处
- ❌ **改老脚本原地** —— 老脚本在 `old_coding/`，按 QWEN.md 约定不原地改
- ❌ **跳过验证步骤** —— 至少跑 `--help` 和语法检查，未连机也要在交付时声明"未实机回归"
- ❌ **改 `2-script-contract.md` 来适配老脚本行为** —— 规范先于代码，反过来就是技术债

## 同步要改的地方

每次新剥一个 step 脚本时**同时**检查：

1. 该机型的 `doc/` 目录：
   - `flash-pipeline.md` — 更新步骤表（含新脚本在流水线中的位置）
   - `troubleshooting.md` — 新增条目标注 `[reason]` 标识符，覆盖已知错误
2. `doc/conventions/02-script-contract.md` — 如果发现新约定没记在规范里，**先改规范**再改代码
3. 任何 hardcode 但应该扒的常量被遗漏 —— 重新走第 1 步
