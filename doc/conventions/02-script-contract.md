# 脚本契约 (Script Contract)

每个步骤脚本（`<数字>.<step>.py`）对外的稳定接口约定。
脚本可独立运行，也可被其他脚本通过 stdin/stdout 组合调用。

> **2026-06-10 方向修订**：AI 是脚本的主要操作者。脚本专注于做一件事并输出结构化 JSON。流程编排和排错走文档（`flash-pipeline.md` / `troubleshooting.md`），不在 JSON 里携带导航信息。

## 通信三件套

| 通道 | 用途 | 格式 |
|------|------|------|
| **stdout** | 机器可读结果 | 单一 JSON 对象 |
| **stderr** | 人类可读进度 | 自由文本 |
| **exit code** | 成功/失败 | `0` 成功 / 非 `0` 失败 |

## stdout 规则

- 最终输出**恰好一个** JSON 对象
- 末尾必须换行
- **不夹杂**其他文本（避免污染 JSON 解析）
- 字段命名遵循 `01-naming.md`

### 顶层字段

```json
{
  "ok": true,               // 必选：成功/失败
  "step": "login_get_stok", // 必选：当前步骤名（与脚本文件名 .step 部分一致）
  "data": { ... },          // 成功时有：结构化业务数据
  "error": "...",           // 失败时有：人类可读错误详情
  "reason": "stok_expired", // 失败时推荐：标准化错误分类标识
  "recoverable": true,      // 失败时推荐：AI 能否自动恢复
  "duration_ms": 1234       // 可选：脚本执行耗时
}
```

### 成功输出

```json
{
  "ok": true,
  "step": "login_get_stok",
  "data": {
    "stok": "xxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "ip": "192.168.31.1",
    "encrypt_mode": 0,
    "key_source": "fetched from init.<hash>.js"
  }
}
```

业务数据由各脚本自行定义，全部 snake_case。字段要自描述，AI 不需额外上下文就能理解。

### 失败输出

```json
{
  "ok": false,
  "step": "enable_ssh",
  "error": "stok expired (HTTP 401 from /api/misystem/set_config_iotdev)",
  "reason": "stok_expired",
  "recoverable": true
}
```

| 字段 | 必选 | 类型 | 说明 |
|------|------|------|------|
| `error` | ✅ | string | 人类可读错误详情（含 HTTP 状态码、API 返回等上下文） |
| `reason` | 推荐 | string | 标准化分类标识（见下方分类表），AI 用此字段查 `troubleshooting.md` |
| `recoverable` | 推荐 | bool | AI 能否自动恢复。`true`=可重试某步，`false`=需人工介入 |

`error` 要写足上下文——AI 用这段文本配合 `reason` 在 `troubleshooting.md` 里定位恢复步骤。

### 错误分类

`reason` 字段使用下列标准化标识符。AI 用 `reason` 查 `doc/troubleshooting.md` 获取详细恢复步骤：

| reason | 含义 | recoverable |
|--------|------|-------------|
| `stok_expired` | stok 令牌过期 | true |
| `not_inited` | 路由器未初始化 | true |
| `already_inited` | 路由器已初始化 | true |
| `network_unreachable` | 路由器不可达 | true |
| `auth_failed` | 密码错误 | true |
| `firmware_rejected` | 固件上传/刷写被拒 | false |
| `ssh_failed` | SSH 连接失败 | true |
| `mtd_write_failed` | MTD 写入失败 | false |
| `file_not_found` | 文件缺失 | true |
| `smartcontroller_unavailable` | smartcontroller 漏洞链路已堵死 | false |
| `unknown` | 未分类错误 | false |

分类表随 `doc/troubleshooting.md` 扩展。`troubleshooting.md` 按 `[reason]` 索引条目，AI 通过 `reason` 字段快速定位恢复方案。

## stderr 规则

- 自由文本，给操作员看
- 推荐格式：`<时间> [<LEVEL>] <消息>`
  - 例：`2026-06-08T10:00:00Z [INFO] GET /api/xqsystem/init_info → 200`
- 进度、警告、调试信息都走这里
- **不写**结果数据
- **默认静默**——不传 `--debug` 时 stderr 一片空白
- `--debug` 开启时打印进度日志

## exit code

| Code | 含义 |
|------|------|
| `0` | 成功 |
| `1` | 通用错误 |
| `2` | 参数错误（argparse 默认） |
| `3` | 网络错误 |
| `4` | 认证失败 |
| `5` | 超时 |
| `>= 10` | 脚本自定义（见各脚本文档） |

## 命令行参数

- 全部走 `argparse`
- 必须支持 `--help`（不写就是 bug）
- 必须支持 `--help-json`：输出参数 JSON Schema，供 AI 自动构造命令行
- 必填参数显式标 `required=True`
- 短选项 `-h` 已被 argparse 占用，别再用
- 标准开关：
  - `--debug`：打印进度日志到 stderr（**默认关闭**——成功时只输出 JSON）
  - `--timeout <sec>`：网络超时（默认 30）
  - `--ip <IP>`：路由器 IP（默认 `192.168.31.1` 小米 stock 固件；`192.168.1.1` OpenWrt 阶段脚本，以各脚本实际代码为准）

### --help-json 输出规范

`--help-json` 的输出是一个 JSON 对象，描述脚本的所有参数：

```bash
$ python3 2.login_get_stok.py --help-json
{
  "script": "login_get_stok",
  "description": "AX3600 步骤 2：登录并获取 stok",
  "args": [
    {
      "name": "--ip",
      "type": "string",
      "default": "192.168.31.1",
      "required": false,
      "description": "路由器 IP"
    },
    {
      "name": "--pwd",
      "type": "string",
      "default": null,
      "required": true,
      "description": "管理员密码"
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
    "python3 2.login_get_stok.py --pwd adminpass123",
    "python3 2.login_get_stok.py --pwd adminpass123 --debug"
  ],
  "stdin_contract": {
    "expects": "上游 JSON（含 data.stok），可省略",
    "produces": "含 data.stok 的成功 JSON"
  }
}
```

AI 拿到这个 JSON 后，可以直接解析参数列表、判断哪些必填、自动构造命令行。

## 输入来源优先级

1. **网络自动探测**（无状态，首选）
2. **命令行参数**（确定性输入）
3. **stdin JSON**（链式调用，跨脚本传递）

## 临时文件

- 用 `tempfile.NamedTemporaryFile`
- **不污染**当前目录
- 退出时清理（`try/finally` 或上下文管理器）

## 依赖

- 优先标准库
- 三方库在文件顶部 `import` 区集中声明
- 不写隐式依赖：脚本不假定 venv 已激活，缺包时大声报错

## 链式调用

```bash
python3 ./1.detect.py | python3 ./2.init.py
```

约定：上一个脚本 stdout 喂给下一个 stdin 即可。
具体协议见各脚本 `--help`。

## 示例

**独立运行**
```bash
$ python3 ./1.check_miwifiapi.py
{"ok": true, "step": "check_miwifiapi", "data": {"model": "AX3000T", "is_inited": true}}
$ echo $?
0
```

**链式调用**
```bash
$ python3 ./1.check_miwifiapi.py 2>/dev/null | python3 ./2.auto_init.py
{"ok": true, "step": "auto_init", "data": {"inited": true}}
```

**默认就是静默——无需 `--quiet`，管道流直接拿 JSON**
```bash
$ python3 ./1.check_miwifiapi.py | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['data']['model'])"
AX3000T
```

**调试时显式开日志**
```bash
$ python3 ./1.check_miwifiapi.py --debug 2>&1 | less
```

**AI 驱动：先查 --help-json 再构造参数**
```bash
# AI 查询参数 Schema，决定该传什么参数
$ python3 ./2.login_get_stok.py --help-json
{"script": "login_get_stok", "args": [{"name": "--pwd", "required": true, ...}]}

# AI 根据 Schema 补全参数并调用
$ python3 ./2.login_get_stok.py --pwd 'mypassword'
{"ok": true, "step": "login_get_stok", "data": {"stok": "xxx"}}

# AI 查阅 flash-pipeline.md 决定下一步；执行失败时查 troubleshooting.md 恢复
```

## 文档要求

每个步骤脚本必须在同机型目录 `doc/` 下有对应的文档引用。AI 通过文档补全决策上下文：

| 文档 | 用途（AI 视角） |
|------|----------------|
| `flash-pipeline.md` | 整体流程：先做什么后做什么，决策分支 |
| `enable-ssh.md` | 开 SSH 的具体方法、版本依赖、注意事项 |
| `troubleshooting.md` | 遇到错误时查表：`reason` → 恢复步骤 |
| `model-info.md` | 硬件参数：Flash 布局、MTD 映射、加密模式 |

AI 不硬编码路由器知识（如 MTD 分区号、Key/IV），而是从文档和运行时探测中获取。
`troubleshooting.md` 是 AI 排错的主要知识来源，文档必须随脚本同步更新。
