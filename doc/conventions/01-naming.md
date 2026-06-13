# 命名约定 (Naming Conventions)

本项目所有标识符的命名规则。一致性 → 可读性 → 可维护性。

## 目录与文件

| 类别 | 规则 | 示例 |
|------|------|------|
| 机型目录 | 小写 + 连字符 | `cr660x/`, `jgc-q10/`, `ax3000t/` |
| 步骤脚本 | `<数字>.<动词短语>.py` | `1.check_miwifiapi.py`, `2.auto_init.py` |
| 资源目录 | 小写，复数 | `doc/`, `files/` |
| 文档文件 | `<数字>-<主题>.md` | `01-naming.md`, `02-script-contract.md` |

### 数字前缀

- 一律从 `1` 开始，单步递增
- 数字 + 英文句点 + 动词短语（`1.check_miwifiapi.py`）
- 数字前补零可选（`01` / `1` 都接受），但同一目录下风格必须统一
- 数字反映**逻辑顺序**，不是"调用次数"
- 数字可跳：缺号表示该步有可选项
- 数字不代表依赖关系（脚本自身可独立运行）

## Python 标识符

| 类别 | 规则 | 示例 |
|------|------|------|
| 模块/包 | 小写下划线 | `check_miwifiapi` |
| 函数/变量 | 小写下划线 (snake_case) | `detect_router`, `is_inited` |
| 常量 | 大写下划线 | `KEY`, `IV`, `MAX_RETRY` |
| 类 | 大驼峰 (PascalCase) | `RouterSession`, `StageResult` |
| 私有 | 单下划线前缀 | `_internal_state` |
| 魔法 | 双下划线包裹 | `__init__` |

## JSON 字段

- 全部 snake_case
- 布尔值用 `is_` / `has_` 前缀：`is_inited`, `has_ssh`
- 状态枚举用名词：`status: "ok" | "fail" | "pending"`
- 时间戳用 ISO 8601：`2026-06-08T10:00:00Z`
- 不使用简写：prefer `password` over `pwd`
  - 例外：`stok`、`nonce` 已是行业约定，保留

## 网络与设备标识

| 类别 | 格式 | 示例 |
|------|------|------|
| IP | 字符串 | `"192.168.31.1"`（stock）/ `"192.168.1.1"`（OpenWrt） |
| 端口 | int | `80` |
| MAC | 冒号分隔 | `"a0:39:00:xx:xx:xx"` |
| SSID | 字符串原样 | `"Xiaomi_XXXX"` |

## 严禁

- ❌ 拼音、混合大小写（如 `getMyName`、`getZhongWen`）
- ❌ 缩写到不可读（避免 `cfg`, `mgr`；用 `config`, `manager`）
- ❌ 数字后缀区分相似变量（`router1`, `router2` → 用列表/字典）
- ❌ 单字母变量（循环 `i, j` 例外）

## 注释

- 文件首行简短描述职责（不写修改历史，由 git 记录）
- 函数 docstring 写**做什么**和**返回什么**，不写**怎么实现**
- 注释解释"为什么"，不解释"是什么"——代码自解释
