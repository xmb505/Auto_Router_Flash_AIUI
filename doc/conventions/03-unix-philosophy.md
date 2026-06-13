# Unix 哲学总则 (Unix Philosophy)

本项目代码风格的精神指南。源自 Doug McIlroy / Ken Thompson / Rob Pike 的经典论述。

> **2026-06-10 方向修订补充**：AI 是这些原则的主要受众。以下每条原则在 AI 驱动项目中的解读：

| 原则 | AI 语境下的重点 |
|------|----------------|
| 模块化 | 每个脚本的 JSON 输出自包含，不依赖 AI 记忆上下文 |
| 组合 | stdin/stdout JSON 管道 = AI 最容易解析的协议 |
| 静默 | 默认不输出废话，JSON 是唯一契约 |
| 透明 | 失败时的 JSON 要解释清楚，不靠 AI 猜 |
| 修复 | 不仅要哭，还要告诉 AI"下一步该怎么做" |

## 核心原则

### Rule of Modularity — 写简单的部件，用干净的接口连接

每个脚本只做一件事。**一件事**的标准：
- 一句话能说清它的职责
- 函数体不超过一屏
- 没有"如果情况 X 就做 A，情况 Y 就做 B"的多分支逻辑

### Rule of Composition — 设计让程序能相互连接

脚本之间通过 stdin/stdout 串联，JSON 作为数据格式。
**不发明**新的通信协议——就用 shell 管道 + JSON。

### Rule of Separation — 分离策略与机制，分离接口与引擎

| 层级 | 职责 | 位置 |
|------|------|------|
| **机制** | 怎么发 HTTP 请求、怎么 SSH 登录、怎么 mtd 写 | `core/`（未来） |
| **策略** | 先 SSH 再烧 uboot 还是反过来 | 步骤脚本 |
| **接口** | 对外的 JSON 字段、参数、退出码 | 见 `02-script-contract.md` |

### Rule of Simplicity — 设计简单，添加复杂性只为真实需求

> 如无必要，勿增复杂度

能用 20 行解决就别写 200 行。**重构的时机是"第二次重复"，不是"预先抽象"。**

### Rule of Parsimony — 不写大程序

大程序 = 难读 + 难调 + 难测。**小**才是美德。

### Rule of Transparency — 设计可见性

- 进度**条件性**走 stderr（**默认关闭**，需显式 `--debug` 才看得到）
- 中间结果写文件（必要时），方便人肉检查
- 不用花哨的"黑盒"
- **不要靠 stderr 日志来诊断**——日志是辅助，JSON 才是契约。失败/成功的真相在 stdout 的 `ok` 字段里。

### Rule of Robustness — 鲁棒性是清晰和简单的孩子

复杂代码自然脆弱。简单 + 边界清晰 = 鲁棒。

### Rule of Representation — 把知识折叠进数据

能用配置/JSON 描述的逻辑，就别写死在代码里。
**例外**：性能敏感的路径。

### Rule of Least Surprise — 惊喜最小化

新读者读你的脚本第一眼应该觉得"理所当然"。

### Rule of Silence — 没意外输出即是好事

成功的时候闭嘴——只输出 JSON 即可。
**别在 stdout 打** "OK!"、"Done!"、emoji ✨。

### Rule of Repair — 失败时大声哭出来

**在 JSON 里**——`{"ok": false, "step": "...", "error": "..."}`，错误写在 `error` 字段，exit code 非 0。
**不在 stderr 里**——默认静默，stderr 失败时也不输出（除非 `--debug`）。
- 失败在哪一步 → `step` 字段
- 错误码 / 异常类 → `error` 字段
- 可重试？要不要手动介入 → 写进 `error` 文本里
- 调用方只看 JSON 就能决策下一步，不用解析日志

### Rule of Economy — 程序员的时间宝贵

- 写 1 行能跑就别写 3 行
- 用现成的（标准库、argparse、rich）
- 但别为了省事留下技术债

### Rule of Generation — 避免手工编程

能用脚本生成脚本的地方就用脚本。
> 例：6 个机型的目录结构 → 一行 `for` 循环就建好。

### Rule of Optimization — 先做出能跑的原型，再优化

1. 第一版：能跑通刷机流程
2. 第二版：补错误处理
3. 第三版：补日志
4. 第四版：补参数化

跳过前三步直接优化 = 浪费时间。

### Rule of Diversity — 怀疑"单一最佳方式"

- 不强求所有机型用同一套脚本
- CR660X 是 CR660X，AX3000T 是 AX3000T——按需设计
- **只在它们真的等价时**才抽象

### Rule of Extensibility — 为未来扩展设计

- **接口**（契约）一旦定下来就稳定
- 内部实现可以重写
- 出口/入口（stdin/stdout/exit code）= 接口

## 实践清单

新建一个步骤脚本时，自查：

- [ ] 命名遵循 `<数字>.<动词>.py`？
- [ ] `--help` 可用？
- [ ] `--help-json` 可用，输出正确参数 Schema？
- [ ] stdout 输出恰好一个 JSON？
- [ ] **默认静默**——不传 `--debug` 时 stderr 一片空白？
- [ ] argparse 暴露 `--debug`（action="store_true"）？
- [ ] exit code 用 0/非 0 表达成功/失败？
- [ ] 不依赖标准库以外的库？（如依赖已声明）
- [ ] 一句话能说清职责？
- [ ] 失败时 JSON 包含 `error` + `reason` + `recoverable`？
- [ ] 能独立运行：`python3 ./N.xxx.py`？
- [ ] 管道友好：`script.py | jq .data` 能直接拿到结果？
- [ ] `doc/troubleshooting.md` 覆盖了本脚本的已知错误？

## 本项目语境下的权衡

| 原则 | 路由器刷机的特殊性 | 我们的取舍 |
|------|-------------------|-----------|
| 鲁棒性 | 刷机失败 = 变砖 | 失败时大声报错（在 JSON 里），宁可中断也不可继续 |
| 静默 | 操作员需要看进度 vs 管道流要求干净 | **默认静默**；`--debug` 显式开进度；JSON 始终是契约 |
| 简单 | 各机型协议差异大 | 不强求统一脚本，承认机型差异 |
| 透明 | 刷机过程要可信 | `--debug` 时进度详细、临时文件可追；JSON 字段完整 |
| 组合 | 部分步骤必须原子（如 mtd 写） | 单步脚本独立，但 `flash_openwrt.sh` 这种"批次脚本"允许非原子 |
| 修复 | 操作员需要知道下一步怎么办 | `error` 字段写明"可重试？要不要手动介入" |
| 闭门造车 | 没实物也想写代码，项目早期人员有这个冲动 | **不允许**。没真机就只搭骨架（doc/ files/），步骤脚本写到一半也是废物——协议细节、MTD 分区、加密行为全部靠实测，不能靠猜 |

## 参考

- [Eric Raymond, *The Art of UNIX Programming*](http://www.catb.org/~esr/writings/taoup/)
- [Doug McIlroy: *A Quarter Century of Unix*](https://www.cs.dartmouth.edu/~doug/)
- [Rob Pike: *Notes on Programming in C*](https://www.lysator.liu.se/c/pikestyle.html)
- [The Unix Philosophy, summarized](https://en.wikipedia.org/wiki/Unix_philosophy)
