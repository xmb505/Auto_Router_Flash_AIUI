# AI 接口设计规范 (AI Interface Design)

> 2026-06-10 确立。AI 是脚本的主要操作者，本规范定义 AI 与步骤脚本之间的交互协议。

AI 通过以下三种方式与脚本交互。每种方式的设计目标一致：**让 AI 不需要硬编码知识就能正确使用脚本**。

---

## 1. 参数发现：`--help-json`

每个步骤脚本必须支持 `--help-json`，输出 JSON Schema 供 AI 自动构造命令行。

### 为什么不是 --help 文本解析？

`--help` 的文本格式是给人看的，不同脚本的格式不能保证一致。AI 解析文本容易出错（换行缩进变化、可选参数标记方式不一）。`--help-json` 是确定性输出，AI 可以直接 `json.loads()`。

### Schema 字段定义

```json
{
  "script": "enable_ssh",
  "step_number": 3,
  "description": "AX3600 步骤 3：通过 set_config_iotdev 注入开 SSH",
  "args": [
    {
      "name": "--ip",
      "type": "string",
      "default": "192.168.31.1",
      "required": false,
      "description": "路由器 IP",
      "value_hint": "小米路由器默认 IP"
    },
    {
      "name": "--stok",
      "type": "string",
      "default": null,
      "required": false,
      "description": "stok 令牌（不传则从 stdin 读）",
      "value_hint": null
    }
  ],
  "stdin_contract": {
    "expects": "上游 JSON（含 data.stok）",
    "produces": "含 ssh_ok 的成功 JSON"
  },
  "pipeline_position": {
    "after": ["login_get_stok"],
    "before": ["official_upgrade", "miwifi_2_openwrt"],
    "alternative_to": null
  }
}
```

| 字段 | 说明 |
|------|------|
| `name` | 参数名（含 `--` 前缀） |
| `type` | `string` / `int` / `bool` / `flag`（布尔开关） / `file`（文件路径） |
| `default` | 默认值（`null` = 无默认值） |
| `required` | 是否必传 |
| `description` | 参数描述 |
| `value_hint` | 给 AI 的值提示（如 `"管理员密码"`），AI 不知道该填什么时参考 |

### AI 的使用模式

```python
# AI 视角下的参数构造流程
import subprocess, json

def discover_args(script_path: str) -> list:
    """查询 --help-json，返回参数列表"""
    result = subprocess.run(
        ["python3", script_path, "--help-json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)["args"]

def construct_command(script_path: str, user_knowledge: dict) -> list:
    """根据 Schema + 用户知识自动补全参数"""
    schema = discover_args(script_path)
    cmd = ["python3", script_path]
    for arg in schema["args"]:
        if arg["name"] in user_knowledge:
            cmd += [arg["name"], user_knowledge[arg["name"]]]
        elif arg["required"] and arg["default"] is None:
            raise ValueError(f"缺少必填参数: {arg['name']} ({arg['description']})")
        elif arg["default"] is not None and arg["type"] != "flag":
            cmd += [arg["name"], str(arg["default"])]
        elif arg["type"] == "flag" and arg["default"] is False:
            pass  # flag 默认关，不加
    return cmd
```

---

## 2. 输出协议

脚本只输出三样东西：**成功/失败**、**业务数据**、**错误分类**。流程编排走文档，不放到 JSON 里。

### 成功输出字段

| 字段 | 必选 | 类型 | 说明 |
|------|------|------|------|
| `ok` | ✅ | bool | `true` |
| `step` | ✅ | string | 当前步骤名（与脚本文件名 .step 部分一致） |
| `data` | ✅ | object | 结构化业务数据，全部 snake_case |
| `duration_ms` | 可选 | int | 脚本执行耗时 |

`data` 字段必须自描述——AI 看字段名和值就能理解含义，不需要外部知识。

### 失败输出字段

| 字段 | 必选 | 类型 | 说明 |
|------|------|------|------|
| `ok` | ✅ | bool | `false` |
| `step` | ✅ | string | 当前步骤名 |
| `error` | ✅ | string | 人类可读错误详情（含 HTTP 状态码、API 返回等上下文） |
| `reason` | 推荐 | string | 标准化错误分类标识（见下方分类表） |
| `recoverable` | 推荐 | bool | AI 能否自动恢复 |

`error` 字段要写足上下文。AI 用 `reason` 定位 `troubleshooting.md` 中的条目，用 `error` 的细节确认匹配。

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

---

## 3. 错误排查集成：`troubleshooting.md`

AI 不靠猜测排错，而是查阅 `doc/troubleshooting.md`。

### 文档格式约定

`troubleshooting.md` 的每个条目遵循固定格式，方便 AI 解析：

```markdown
## [stok_expired] STOK 令牌过期

**现象**：调用 /api/misystem/set_config_iotdev 返回 HTTP 401

**原因**：stok 有效期约 30 分钟，超时后需重新登录

**恢复步骤**：
1. 重新运行 2.login_get_stok.py 获取新 stok
2. 用新 stok 重试失败步骤

**recoverable**：true
**相关脚本**：login_get_stok, enable_ssh
```

格式约定：
- 标题行 `## [<reason>] <描述>` — `reason` 字段就是查找键
- `**恢复步骤**：` — 有序列表，具体可执行的命令
- `**recoverable**：` — true/false
- `**相关脚本**：` — 逗号分隔的脚本名列表

### AI 排错流程

```
步骤脚本返回 {"ok": false, "reason": "stok_expired", "recoverable": true}
    │
    ▼
AI 查 doc/troubleshooting.md 搜索 [stok_expired] 标题
    │
    ▼
读取恢复步骤 → 执行 login_get_stok
    │
    ▼
用新 stok 重试原步骤
    │
    ▼
成功 → 按照 flash-pipeline.md 继续流水线
失败 → 查 troubleshooting.md 再试下一级恢复方案，或终止并告知用户
```

---

## 4. Orchestrator 接口（规划）

未来将有一个轻量 orchestrator（`src/orchestrator.py`），AI 通过它驱动整个流水线：

```bash
# AI 指定目标，orchestrator 自动编排
$ python3 orchestrator.py --model ax3600 --target openwrt --pwd admin123
```

orchestrator 遵循相同的 JSON 协议：

```json
{
  "ok": true,
  "step": "orchestrator",
  "data": {
    "target": "openwrt",
    "model": "ax3600",
    "current_step": 4,
    "steps_completed": ["official_init", "login_get_stok", "enable_ssh"],
    "remaining_steps": ["official_upgrade", "miwifi_2_openwrt"],
    "state": {
      "stok": "xxx",
      "ssh_ok": true,
      "current_partition": "rootfs"
    }
  }
}
```

详细设计见后续文档。

---

## 设计准则

1. **输出即事实**：JSON 输出只表达执行结果和业务数据，不做编排导航。流程信息在文档里。
2. **错误即可恢复性必须明确**：每个错误输出必须告诉 AI"这个能不能自动重试"。不能恢复的要明确说不能。
3. **不要假设 AI 有记忆**：每个 JSON 输出包含足够上下文，不依赖 AI 记住前几步的返回。
4. **文档即知识库**：AI 排错不靠训练数据中的知识，靠 `troubleshooting.md`。文档和脚本必须同步更新。
5. **最低惊讶原则**：AI 是严格解析器，比人类更不能容忍歧义。JSON 字段名、类型、可选性必须精确。

## 严格标准清单

新增/修改脚本时，对照检查：

- [ ] `--help-json` 支持？
- [ ] 成功 JSON 字段齐全（ok + step + data）？
- [ ] 失败 JSON 包含 `reason`、`recoverable`？
- [ ] 同机型 `doc/troubleshooting.md` 覆盖本脚本的已知错误？
- [ ] 所有 JSON 字段名 snake_case？
- [ ] 错误信息人类可读（不只 code 数字，要带上下文），AI 可解析（reason 分类）？
- [ ] `flash-pipeline.md` 说明了本脚本在流水线中的位置？
