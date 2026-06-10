# 工具脚本契约 (Utility Script Contract)

辅助 / 调试脚本的稳定接口约定。**会被 step 脚本调**，不是只人跑。

## 适用对象

`src/project/<model>/` 下除 `N.step.py` 外的 `.sh` / `.py` 脚本：

| 类型 | 例子 |
|------|------|
| 探针 | `get_router_info.sh` |
| 交互式 | `miwifi_ssh.sh` |
| 上传工具 | `4.firmware_upload_on_miwifi.sh` |
| 状态检测 | `check_boot_partition.sh` |
| 配置改写 | `set_uboot_env.sh` |
| 恢复出厂 | `router_official_recovery.sh` |

## 与 step 脚本的差异

| 维度 | step 脚本（`02-script-contract.md`） | 工具脚本（本文件） |
|------|------|------|
| 命名 | 必有 `N.` 数字前缀 | 多数**无**前缀（数字会被误读为 pipeline 步骤）|
| 调用方 | 人工 / orchestrator | step 脚本 / 人工 / orchestrator |
| 输出 | 单 JSON（一次调用） | 同左 |
| 写路由器状态 | 多数是 | 看具体脚本（探针类只读）|
| 链式调用 | 是 | 是 |

> **命名例外**：`4.firmware_upload_on_miwifi.sh` 带数字 4.——user 明确要求。
> 后续工具脚本默认不带数字，**除非 user 明确指定**。

## 命令行约定

### 通用开关（所有工具脚本**必有**）

| Flag | 默认 | 说明 |
|------|------|------|
| `--ip <IP>` | `192.168.31.1` | 路由器 IP（小米 DHCP 网关约定）|
| `--ssh-pwd <密码>` | `root` | SSH root 密码（dev shortcut）|
| `--debug` | 关 | 保留 stderr（含 SSH 错误、scp 进度条等）|
| `-h, --help` | — | 从脚本头注释提取帮助 |

### 业务开关

- **必传**：用 `required=True` 或空默认值 + 显式 `if [ -z ... ]` 检查
- **可选**：用**字面默认值**（dev shortcut），不读环境变量/配置文件
- 例外：`--file <本地文件>` 这类**完全用户配置**字段才 `required=True`

## 输出约定

### stdout = **单个 JSON 对象**

**成功**：
```json
{"ok": true, "ip": "192.168.31.1", ...业务字段}
```

**失败**：
```json
{"ok": false, "ip": "192.168.31.1", "error": "..."}
```

### 顶层字段（**强制**）

| 字段 | 类型 | 必有 | 说明 |
|------|------|------|------|
| `ok` | bool | ✅ | 成功 `true` / 失败 `false` |
| `ip` | str | ✅ | 路由器 IP（即使失败也回，让调用方能定位）|
| `error` | str | 失败时 | 错误原因，**仅失败时存在** |
| 业务字段 | — | — | snake_case，按需扩展 |

### 业务字段命名

- 全部 snake_case
- 布尔：`is_` / `has_` 前缀（`is_inited`, `has_ssh`）
- 状态枚举：名词（`"ok"`, `"fail"`, `"unknown"`）
- 集合 / 表：`{...}`（如 `set`, `verified`, `ubi_info`）

### stderr 约定

- 默认 **空**（`2>/dev/null` 整体丢 / `sed -u '/^Warning/d' >&2` 过滤特定行）
- `--debug` 时**保留全部**
- **不**写结果数据（结果在 stdout JSON 里）

### exit code

| Code | 含义 |
|------|------|
| `0` | 成功 |
| `1` | 通用错误（SSH 失败、命令失败等）|
| `2` | 参数错误（`--help`、未知 flag、缺必传）|
| `>= 3` | 脚本自定义（看 `--help` 输出）|

> **管道友好**：调用方可以 `if ./util.sh; then ...` 而不依赖 stdout 解析

## 被 step 脚本调用的模式

### Python (step.py 调 utility.sh)

```python
import subprocess, json

def call_util(*args, ip="192.168.31.1", ssh_pwd="root"):
    p = subprocess.run(
        ["./util.sh", "--ip", ip, "--ssh-pwd", ssh_pwd] + list(args),
        capture_output=True, text=True, check=False
    )
    out = json.loads(p.stdout) if p.stdout.strip() else {"ok": False, "error": "empty"}
    if not out.get("ok"):
        raise RuntimeError(f"util.sh failed: {out.get('error')}")
    return out  # 整 JSON 或 out["data"]
```

### Bash (orchestrator 调 utility.sh)

```bash
result=$(./util.sh --ip 192.168.31.1 --ssh-pwd root)
if ! echo "$result" | jq -e .ok >/dev/null; then
  echo "[ERROR] util.sh failed: $(echo "$result" | jq -r .error)" >&2
  exit 1
fi
# 提取业务字段
target=$(echo "$result" | jq -r .target)
```

## 实践清单

新增工具脚本时自查：

- [ ] 有 `--ip` / `--ssh-pwd` / `--debug` / `-h|--help`？
- [ ] 顶层 JSON 必有 `ok` + `ip`？
- [ ] 失败时 `ok=false` + `error` 字段 + 非零 exit？
- [ ] 默认 stdout 干净（`--debug` 才显示详细）？
- [ ] 字段名 snake_case，集合用 `{...}`？
- [ ] 路由器 IP 字段**统一叫 `ip`**（不是 `router_ip` / `host` / `address`）？
- [ ] 错误消息**人类可读**（不只 `code: 1523`，还要说"nonce 验证错误"之类）？
- [ ] **SSH 连接不自己造轮子**——通过 `miwifi_ssh.sh --cmd` 复用（见下节）？

## 工具脚本之间的依赖（SSH 复用）

**所有工具脚本的 SSH 连接必须通过 `miwifi_ssh.sh`**，不要自己写 `sshpass + ssh -o...`：

```
src/project/<model>/
├── miwifi_ssh.sh        ← SSH 底层（连接配置 / sshpass / 警告抑制）
├── set_uboot_env.sh     ← 调 miwifi_ssh.sh --cmd '...'
├── check_boot_partition.sh  ← 调 miwifi_ssh.sh --cmd '...'
├── get_router_info.sh    ← HTTP 探针（不用 SSH，独立）
├── 4.firmware_upload_on_miwifi.sh  ← 调 sshpass + scp（不走 miwifi_ssh）
└── ...
```

**原因**：
- 改 SSH 选项（比如换 host key 算法、加 `-O`、加 `StrictHostKeyChecking`）→ **只改一个文件**
- 所有工具脚本的 SSH 行为**统一**（warning 处理、错误处理、JSON 格式）
- **避免复制粘贴漂移**（5 个工具脚本每个写一份 SSH 配置，某天改了一个忘了改另一个）

**怎么调**：

```bash
# 同目录下
"$SCRIPT_DIR/miwifi_ssh.sh" --ip "$ip" --pwd "$ssh_pwd" --cmd 'nvram get foo'
```

- `--cmd` 可重复传多条（每条独立 SSH，返回 JSON 数组）
- 每条命令的 JSON 字段：`ok`, `cmd`, `exit_code`, `stdout`, `stderr`
- 解析远端输出用 `python3 -c 'import sys,json; arr=json.load(sys.stdin); print(arr[0]["stdout"])'`

**例外**：
- `4.firmware_upload_on_miwifi.sh` 用 `scp`（不是交互式 SSH），所以不通过 miwifi_ssh
- `miwifi_ssh.sh` **自己**就是 SSH 底层，**不调自己**

## 当前 ax6 工具脚本索引

| 脚本 | SSH 来源 | 主要 JSON 字段 | 备注 |
|------|---------|---------------|------|
| `miwifi_ssh.sh` | （自身） | 无 cmd 时 exec 替换 shell；有 `--cmd` 时返回 `[{ok, cmd, exit_code, stdout, stderr}]` | SSH 复用组件，**所有 SSH 工具都调它** |
| `get_router_info.sh` | （HTTP） | 透传 init_info 完整 JSON | 探针，不用 SSH |
| `4.firmware_upload_on_miwifi.sh` | 自带 scp | `ok`, `file`, `target`, `ip` | 有数字 4.（user 指定）；scp 不走 miwifi_ssh |
| `set_uboot_env.sh` | **调 miwifi_ssh** | `ok`, `mode`, `ip`, `set{...}`, `verified{...}` | set vs verified 比对 |
| `check_boot_partition.sh` | **调 miwifi_ssh** | `ok`, `current_partition`, `current_mtd`, `consistency` | 不靠 nvram 判当前 |
| `router_official_recovery.sh` | （HTTP） | （默认静默，exit code 表达）| 失败时 stderr 输出 body |
