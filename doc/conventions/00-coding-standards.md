# Auto Router Flash AIUI — 编程规范总纲

> 整合自 `01-naming.md` ～ `05-ai-interface.md` 及实际代码模式。
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

### 文件与目录

| 类别 | 规则 | 示例 |
|------|------|------|
| 机型目录 | 小写 + 连字符 | `cr660x/`, `ax3600/`, `newifid2/` |
| 步骤脚本 | `<数字>.<动词短语>.py` | `1.official_init.py`, `2.login_get_stok.py` |
| 工具脚本 | 无数字前缀 | `miwifi_ssh.sh`, `get_router_info.sh`, `set_uboot_env.sh` |
| 资源目录 | 小写复数 | `doc/`, `files/` |
| 规范文档 | `<数字>-<主题>.md` | `01-naming.md`, `02-script-contract.md` |

**例外**：`4.firmware_upload_on_miwifi.sh` 带数字 4.——user 明确指定。

### Python 标识符

| 类别 | 规则 | 示例 |
|------|------|------|
| 函数/变量 | snake_case | `detect_router`, `is_inited` |
| 常量 | UPPER_CASE | `KEY`, `MAX_RETRY`, `STEP_NAME` |
| 类 | PascalCase | `RouterSession` |
| 私有 | `_` 前缀 | `_internal_state` |
| 模块级 DEBUG | `DEBUG` | `DEBUG = False` |

### JSON 字段

- 全部 `snake_case`
- 布尔用 `is_` / `has_` 前缀：`is_inited`, `has_ssh`
- 状态枚举用名词：`"ok"`, `"fail"`, `"pending"`
- 不用简写（`password` not `pwd`），除非行业约定（`stok`, `nonce`）
- 路由器 IP 字段统一叫 `ip`（不是 `router_ip` / `host` / `address`）

### 严禁

- ❌ 拼音、驼峰命名（在 Python/JSON 中）
- ❌ 单字母变量（循环索引除外）
- ❌ 数字后缀区分变量（用列表/字典）

---

## 四、步骤脚本契约（`N.step.py`）

### 4.1 通信三件套

| 通道 | 用途 | 规则 |
|------|------|------|
| **stdout** | 机器可读结果 | 恰好一个 JSON 对象，末尾换行 |
| **stderr** | 进度日志 | 默认空白；`--debug` 开启 |
| **exit code** | 成功/失败 | 0=成功, 1=通用, 2=参数, 3=网络, 4=认证, 5=超时 |

### 4.2 成功输出

```json
{
  "ok": true,
  "step": "login_get_stok",
  "data": { ... }
}
```

| 字段 | 必选 | 说明 |
|------|------|------|
| `ok` | ✅ | `true` |
| `step` | ✅ | 步骤名，与文件名 `.step` 部分一致 |
| `data` | ✅ | 业务数据，字段自描述 |
| `duration_ms` | 可选 | 执行耗时 |

### 4.3 失败输出

```json
{
  "ok": false,
  "step": "enable_ssh",
  "error": "smartcontroller 链路在 32 秒内未激活",
  "reason": "smartcontroller_unavailable",
  "recoverable": true
}
```

| 字段 | 必选 | 说明 |
|------|------|------|
| `ok` | ✅ | `false` |
| `step` | ✅ | 步骤名 |
| `error` | ✅ | 人类可读，含上下文（HTTP 状态码、API 返回等） |
| `reason` | 推荐 | 标准化分类标识，AI 用此查 `troubleshooting.md` |
| `recoverable` | 推荐 | AI 能否自动恢复 |

### 4.4 错误分类（`reason` 枚举）

| reason | 含义 | recoverable |
|--------|------|-------------|
| `stok_expired` | stok 过期 | true |
| `not_inited` | 未初始化 | true |
| `already_inited` | 已初始化 | true |
| `network_unreachable` | 网络不通 | true |
| `auth_failed` | 密码错误 | true |
| `firmware_rejected` | 固件被拒 | false |
| `ssh_failed` | SSH 不通 | true |
| `mtd_write_failed` | MTD 写入失败 | false |
| `file_not_found` | 文件缺失 | true |
| `smartcontroller_unavailable` | 漏洞链路堵死 | false |
| `unknown` | 未分类 | false |

### 4.5 参数约定

- 全部走 `argparse`
- **必须**支持 `--help` 和 `--help-json`
- **标准开关**：

| Flag | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--ip` | str | `192.168.31.1` | 路由器 IP |
| `--timeout` | int | `30` | 网络超时秒 |
| `--debug` | flag | False | 打印进度到 stderr |

- 输入来源优先级：网络自动探测 > 命令行参数 > stdin JSON

### 4.6 `--help-json` 输出规范

必须输出的 JSON Schema：

```json
{
  "script": "enable_ssh",
  "description": "CR660X 步骤 3：启用 SSH（smartcontroller 漏洞 CVE-2023-26319）",
  "args": [
    {
      "name": "--ip",
      "type": "string",
      "default": "192.168.31.1",
      "required": false,
      "description": "路由器 IP"
    },
    {
      "name": "--debug",
      "type": "flag",
      "default": false,
      "required": false,
      "description": "打印进度日志到 stderr"
    }
  ],
  "examples": [
    "python3 3.enable_ssh.py --stok <stok>"
  ],
  "stdin_contract": {
    "expects": "上游 JSON（含 data.stok）",
    "produces": "含 ssh_port 的成功 JSON"
  }
}
```

---

## 五、工具脚本契约（`.sh`）

### 5.1 通用开关（所有工具脚本必有）

| Flag | 默认 | 说明 |
|------|------|------|
| `--ip <IP>` | `192.168.31.1` | 路由器 IP |
| `--ssh-pwd <PWD>` | `root` | SSH root 密码（dev shortcut） |
| `--debug` | 关 | 保留 stderr |
| `-h, --help` | — | 从脚本头注释提取 |

### 5.2 输出

- **成功**：`{"ok": true, "ip": "192.168.31.1", ...业务字段}`
- **失败**：`{"ok": false, "ip": "192.168.31.1", "error": "..."}`
- `ip` 字段**必含**（失败时也回，让调用方能定位）
- stderr 默认空白，`--debug` 时全量保留

### 5.3 SSH 复用

**所有工具脚本的 SSH 连接必须通过 `miwifi_ssh.sh`**：

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/miwifi_ssh.sh" --ip "$ip" --pwd "$ssh_pwd" --cmd 'command'
```

例外：`4.firmware_upload_on_miwifi.sh` 用 scp（不走 SSH），`miwifi_ssh.sh` 自己是底层。

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

### 8.1 AI 与脚本的交互方式

1. **参数发现**：`python3 N.xxx.py --help-json` → 获取参数 Schema → 补全参数 → 调用
2. **输出解析**：stdout 拿 JSON → 判 `ok` → 提取 `data`
3. **排错**：`ok:false` → 读 `reason` → 查 `doc/troubleshooting.md` 找恢复步骤

### 8.2 troubleshooting.md 格式约定

```markdown
## [stok_expired] STOK 令牌过期

**现象**：调用 /api/misystem/set_config_iotdev 返回 HTTP 401

**原因**：stok 有效期约 30 分钟

**恢复步骤**：
1. 重新运行 2.login_get_stok.py 获取新 stok
2. 用新 stok 重试失败步骤

**recoverable**：true
**相关脚本**：login_get_stok, enable_ssh
```

AI 通过 `[reason]` 标题定位，读取恢复步骤后执行。

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
