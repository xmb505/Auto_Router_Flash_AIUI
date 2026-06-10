# 脚本契约 (Script Contract)

每个步骤脚本（`<数字>.<step>.py`）对外的稳定接口约定。
脚本可独立运行，也可被其他脚本通过 stdin/stdout 组合调用。

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
- 顶层字段推荐：
  ```json
  {
    "ok": true,
    "step": "check_miwifiapi",
    "data": { ... }
  }
  ```
- 失败时 `ok: false`，`error` 字段带原因：
  ```json
  {"ok": false, "step": "auto_init", "error": "stok expired"}
  ```

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
- 必填参数显式标 `required=True`
- 短选项 `-h` 已被 argparse 占用，别再用
- 标准开关：
  - `--debug`：打印进度日志到 stderr（**默认关闭**——成功时只输出 JSON）
  - `--timeout <sec>`：网络超时（默认 30）
  - `--router <ip>`：覆盖默认 IP（默认 192.168.1.1）

> **默认静默** 是项目硬约束。成功路径不向 stderr 写任何东西，只 stdout 一个 JSON。
> 失败时仍然只输出一个 `ok:false` 的 JSON 到 stdout，stderr 一并静默。
> 调用方想要看过程，必须显式传 `--debug`。这是 Rule of Silence 的字面落实。

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
# stderr: 2026-06-08T10:00:00Z [INFO] 检测到路由器 192.168.1.1
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
