# Auto Router Flash AIUI — 编程规范总纲

> 本文件是规范体系的**索引 + 速查**，详细内容见各子文档。
> 变更历史在 git，本文只写现行规则。

---

## 一、项目哲学

本项目遵循 **Unix 哲学**，AI 是主要操作者。

| 原则 | 要点 |
|------|------|
| **模块化** | 每个脚本只做一件事，JSON 自包含 |
| **组合** | stdin/stdout JSON 管道串联 |
| **静默** | 默认不输出废话，JSON 是唯一契约 |
| **透明** | 失败时 JSON 要说清楚，exit code 非 0 |
| **修复** | 不仅要哭，还要告诉 AI "能不能自动恢复"（`reason` + `recoverable`） |
| **简单** | 三次重复才抽象，不做预判式设计 |
| **闭门造车禁止** | 无实物时不写步骤脚本，只搭骨架 |

---

## 二、目录结构

```
src/project/<机型>/         # 按机型组织
├── doc/                    # 机型文档（必须）
│   ├── flash-pipeline.md   #   完整刷机流程
│   ├── enable-ssh.md       #   开 SSH 方法
│   ├── troubleshooting.md  #   错误索引（reason → 恢复步骤）
│   └── model-info.md       #   硬件参数
├── files/                  # 固件 / 资源文件
├── N.step.py               # 步骤脚本（<数字>.<动词短语>.py）
├── <util>.sh               # 工具脚本（多数无数字前缀）
└── miwifi_ssh.sh           # SSH 复用组件（其他脚本调它）
```

---

## 三、命名约定

> → 详见 [`01-naming.md`](01-naming.md)

速查：

- **步骤脚本**: `<数字>.<动词短语>.py`，工具脚本多数无数字前缀
- **Python**: snake_case 函数/变量，UPPER_CASE 常量，PascalCase 类
- **JSON**: snake_case，布尔 `is_`/`has_` 前缀，IP 字段统一叫 `ip`
- **严禁**: 拼音、驼峰、单字母变量（循环索引除外）

---

## 四、步骤脚本契约（`N.step.py`）

> → 详见 [`02-script-contract.md`](02-script-contract.md)

速查：

- **stdout** = 单个 JSON `{"ok": bool, "step": ..., "data"|"error": ...}`
- **stderr** = 默认空白，`--debug` 时打印进度
- **exit code** = 0 成功 / 1 通用 / 2 参数 / 3 网络 / 4 认证 / 5 超时
- **标准开关**: `--ip`, `--timeout`, `--debug`
- 必须支持 `--help` 和 `--help-json`
- 输入来源优先级：网络自动探测 > 命令行参数 > stdin JSON

---

## 五、工具脚本契约（`.sh`）

> → 详见 [`04-utility-contract.md`](04-utility-contract.md)

速查：

- **通用开关**: `--ip`（默认 `192.168.31.1`）、`--ssh-pwd`（默认 `root`）、`--debug`、`-h`
- **输出**: `{"ok": true, "ip": "..."}` / `{"ok": false, "ip": "...", "error": "..."}`
- `ip` 字段必含（失败时也回），stderr 默认空白
- **SSH 复用**: 所有工具脚本的 SSH 连接必须通过 `miwifi_ssh.sh`（例外：scp 脚本、miwifi_ssh 自己）

---

## 六、代码模式（Python 步骤脚本）

### 6.1 文件骨架

```python
#!/usr/bin/env python3
# <机型> 步骤 N：<一句话职责>
#
# 适用机型: <型号> — <SoC>
# 前置: ...
# 后置: ...
# 来源: old_coding/...
#
# 输出: stdout = 单个 JSON  {"ok": bool, "step": ..., "data"|"error": ...}
#       stderr = 默认空白，--debug 时打印进度
#       exit  = 0 成功 / 1 失败

import argparse
import json
import sys
# ... 按需 import，优先标准库

# ============ 常量 ============
DEFAULT_ROUTER_IP = "192.168.31.1"
DEFAULT_TIMEOUT = 30
STEP_NAME = "xxx"
DEBUG = False  # 运行时由 --debug 改写；默认静默（Rule of Silence）

# ============ 日志 / 输出 ============
def log(msg: str, level: str = "INFO") -> None:
    if not DEBUG:
        return
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)

def emit_ok(data: dict) -> None:
    print(json.dumps({"ok": True, "step": STEP_NAME, "data": data},
                     ensure_ascii=False))

def emit_err(error: str, reason: str = "", recoverable: bool = True) -> None:
    out = {"ok": False, "step": STEP_NAME, "error": error,
           "recoverable": recoverable}
    if reason:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=False))

# ============ 业务逻辑 ============
# ... 函数实现 ...

# ============ CLI ============
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 N.xxx.py ...",
    )
    p.add_argument("--ip", default=DEFAULT_ROUTER_IP, help=f"路由器 IP（默认: {DEFAULT_ROUTER_IP}）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"网络超时秒（默认: {DEFAULT_TIMEOUT}）")
    p.add_argument("--debug", action="store_true", help="打印进度日志到 stderr（默认静默）")
    # ... 业务参数 ...
    return p.parse_args()

def main() -> int:
    global DEBUG
    if "--help-json" in sys.argv:
        help_json()
        return 0
    args = parse_args()
    DEBUG = args.debug
    try:
        data = do_work(args)
    except Exception as e:
        log(str(e), level="ERROR")
        emit_err(str(e))
        return 1
    emit_ok(data)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 6.2 关键规则

- **默认静默**：`DEBUG` 是唯一的日志开关标志，没有 `--quiet` / `--verbose`
- **DEBUG 是模块级全局**：在 `main()` 里从 `args.debug` 赋值，不把 debug 参传到每个函数
- **纯标准库优先**，必须的三方库在 import 区声明
- **不写死路由器值**：KEY/IV/加密模式/SSID 全部运行时探测
- **Step 脚本是叶子节点**：不重试、不降级、不做前置检查（上游负责）
- **nvram flag 不权威**：`/proc/cmdline` 才是活跃分区真相
- **`--help-json` 在 argparse 之前处理**：用 `sys.argv` 直接检查，避免 argparse 先报错
- **管道友好**：stdin 读上游 JSON 时检查 `ok` 字段，上游失败要透传而非吞错

### 6.3 stdin 链式调用的标准模式

```python
def read_stok_from_stdin() -> str:
    if sys.stdin.isatty():
        raise RuntimeError("未通过 stdin 管道传入上游 JSON，也未传 --stok")
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("stdin 为空（上游没产出 JSON）")
    d = json.loads(text)
    if d.get("ok") is False:
        raise RuntimeError(f"上游失败: {d.get('error', '未知错误')}")
    value = d.get("data", {}).get("stok", "")
    if not value:
        raise RuntimeError(f"上游 JSON 缺少 data.stok 字段")
    return value
```

### 6.4 HTTP 请求的通用封装

```python
def api_request(base_url, stok, api_path, params=None, timeout=30, post=False):
    url = f"{base_url}/cgi-bin/luci/;stok={stok}/api/{api_path}"
    if post:
        encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=encoded)
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 500:
            return None  # hackCheck 探测等的预期路径
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"{api_path} HTTP {e.code}: {body}") from e
```

### 6.5 注释原则

- 文件首行：简短职责描述（不写修改历史——git 记录）
- 函数 docstring：写**做什么**和**返回什么**，不写**怎么实现**
- 内联注释：只解释 **"为什么"**，不解释"是什么"
- **不要**写观察到的路由器值到文档（如"KEY 在 1.1.10 上是 xxxx"）

---

## 七、Bash 工具脚本模式

```bash
#!/bin/bash
# <脚本名> — <一句话职责>
# 用法: ./xxx.sh [--ip <IP>] [--ssh-pwd <PWD>] [--debug]
# 依赖: 同目录 miwifi_ssh.sh
# 输出: stdout = 单个 JSON

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIWIFI_SSH="$SCRIPT_DIR/miwifi_ssh.sh"

ip="192.168.31.1"
ssh_pwd="root"
debug=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ip)      ip="${2:-}"; shift 2 ;;
    --ssh-pwd) ssh_pwd="${2:-}"; shift 2 ;;
    --debug)   debug=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *)         printf '{"ok": false, "error": "未知参数: %s"}\n' "$1"; exit 2 ;;
  esac
done

# 失败时 printf JSON + exit 1，成功时 printf JSON + exit 0
```

---

## 八、AI 接口集成

> → 详见 [`05-ai-interface.md`](05-ai-interface.md)

速查：

- **参数发现**: `--help-json` 输出参数 Schema，AI 自动构造命令行
- **输出解析**: stdout 拿 JSON → 判 `ok` → 提取 `data`
- **排错**: `ok:false` → 读 `reason` → 查 `doc/troubleshooting.md` 找恢复步骤
- `troubleshooting.md` 按 `[reason]` 标题索引，每条含现象/原因/恢复步骤/recoverable/相关脚本

---

## 九、安全约束

| 规则 | 说明 |
|------|------|
| **不硬编码密码/stok** | 走参数传递 |
| **不开文件服务器** | 容器资源有限，不用 HTTP/TFTP/FTP 传文件 |
| **不刷 uboot/MIBIB** | 用官方 uboot，不动 mtd0-mtd7 |
| **不加载内核模块** | `xmir_patcher.ko` 只在有 shell 后可选 |
| **`set_config_iotdev` 纯字符串注入** | 零文件上传 |
| **SSH host key** | 路由器只提供 `ssh-rsa`，需 `-oHostKeyAlgorithms=+ssh-rsa` |

### 密码默认值

| 场景 | 默认密码 |
|------|---------|
| Stock 固件 SSH | `root` |
| OpenWrt/LibWrt SSH | `admin` |
| 小米出厂管理员 | `admin` |

---

## 十、实践清单

### 新建步骤脚本自查

- [ ] 文件名 `<数字>.<动词短语>.py`？
- [ ] `--help` 和 `--help-json` 都可用？
- [ ] stdout 恰好一个 JSON（ok + step + data）？
- [ ] 失败 JSON 含 `error` + `reason` + `recoverable`？
- [ ] 默认静默——不传 `--debug` 时 stderr 空白？
- [ ] 模块级 `DEBUG` flag，`main()` 里从 `args.debug` 赋值？
- [ ] 纯标准库？（否则 import 区声明）
- [ ] 不写死路由器值（KEY/IV/SSID 全部运行时探测）？
- [ ] 管道友好：`script.py | jq .data` 能拿结果？
- [ ] `doc/troubleshooting.md` 覆盖本脚本已知错误？
- [ ] `flash-pipeline.md` 说明本脚本在流水线中的位置？
- [ ] 机型有实物可测？（无实物只搭骨架）

### 新建工具脚本自查

- [ ] 有 `--ip` / `--ssh-pwd` / `--debug` / `-h`？
- [ ] 顶层 JSON 必有 `ok` + `ip`？
- [ ] SSH 连接通过 `miwifi_ssh.sh`？
- [ ] 字段名 snake_case，IP 字段统一叫 `ip`？
- [ ] 错误消息人类可读？

---

## 十一、机型文档要求

每个 `src/project/<机型>/doc/` 必须包含：

| 文件 | 内容 |
|------|------|
| `flash-pipeline.md` | 完整刷机流程、步骤顺序、决策分支 |
| `enable-ssh.md` | 开 SSH 的方法细节、版本依赖 |
| `troubleshooting.md` | 按 `[reason]` 索引的错误恢复方案 |
| `model-info.md` | SoC、Flash 布局、MTD 表、加密模式 |
