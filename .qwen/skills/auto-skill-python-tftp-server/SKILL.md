---
name: python-tftp-server
description: 纯 Python 独立 TFTP 服务器——替代系统 dnsmasq/atftpd，为 uboot TFTP recovery 场景提供常驻文件分发服务，自动绑定兄弟 files/ 目录
source: auto-skill
extracted_at: '2026-06-14T05:06:15.352Z'
---

# 纯 Python 独立 TFTP 服务器

## 适用场景

项目中某路由器需要 uboot TFTP recovery（如 AX3000T 刷机流程步骤 6），但：

- 不想依赖系统包 `dnsmasq`/`atftpd`（需 sudo 安装、可能不存在）
- 旧代码用 `subprocess` 调 `in.tftpd`，传完文件后进程退出（或步骤脚本生命周期结束导致 TFTP 终止）
- 需要常驻后台，多个路由器轮流从同一台服务器拉取固件
- 项目规范要求 Unix 哲学："做一件事、进度走 stderr、输出走 JSON"

## 解决方案

在 `service/tftp/` 下写一个纯 Python TFTP 服务器，作为项目通用的固件分发服务：

```
service/tftp/
├── tftp_server.py    # 独立 TFTP 服务器
└── files/            # 默认固件目录（自动绑定为 TFTP 根目录）
```

## 设计原则

| 原则 | 实现 |
|------|------|
| **常驻** | selectors 事件循环，传完一个客户端继续等下一个 |
| **同级 files/** | 默认 `SCRIPT_DIR + "/files"`，不需手动配根目录 |
| **纯 Python** | 只 `socket` + `selectors` + `struct`，零系统依赖 |
| **多客户端** | per-client 状态机（`TftpSession`），各客户端独立跟踪块号/重试 |
| **路径安全** | `os.path.normpath` + 前缀检查，防止 `../` 越界 |
| **守护化** | `--daemon` 标志 fork 到后台 |
| **契约合规** | `--help-json`, stdout = JSON schema, stderr = 日志 |
| **可指向** | `--root` 参数可指向任意机型固件目录（如 `src/project/ax3000t/files`）|

## 关键实现决策

### 1. TFTP 协议实现（RFC 1350 子集）

只实现 RRQ（读请求），不处理 WRQ（写请求）：

```
客户端 → 服务器:  RRQ (opcode=1,  filename,  mode)
服务器 → 客户端:  DATA (opcode=3,  block#,  payload 0-512B)
                 ACK (opcode=4,  block#)
                 ERROR (opcode=5,  code,  message)
```

- 数据块 512 字节，最后一块 < 512 表示传输完成
- 块号 16 位无符号整数，溢出回 1
- 5 秒 ACK 超时，最多重试 5 次后放弃

### 2. selectors 事件循环（单线程并发）

```python
sel = selectors.DefaultSelector()
sel.register(sock, selectors.EVENT_READ)

sessions = {}  # (client_ip, client_port) → TftpSession

while running:
    events = sel.select(timeout=1.0)
    # 1. 处理超时会话（重试/清理）
    # 2. 处理新 RRQ → 创建 session，发第一块
    # 3. 处理已有会话的 ACK → 发下一块或标记完成
```

### 3. TftpSession 状态机

```
IDLE → handle_rrq() → send_first_block()
                       ↓
                  SENT → handle_ack() → send_next_block() → SENT
                       |                                  ↓
                       |                            (data < 512)
                       |                                  ↓
                       +──────────────────────────→ DONE → stale → CLEANUP
                       
                           handle_timeout() → retry → SENT
                                           → abort → CLEANUP
```

## 用法模板

```bash
# 1. 前台调试（绑定 service/tftp/files/）
sudo python3 service/tftp/tftp_server.py --debug

# 2. 非 root（高端口）
python3 service/tftp/tftp_server.py --port 9999 --debug

# 3. 后台服务
sudo python3 service/tftp/tftp_server.py --daemon

# 4. 指向其他机型固件目录
sudo python3 service/tftp/tftp_server.py --root src/project/ax3000t/files --debug

# 5. 停止
pkill -f tftp_server.py
```

## 与旧方案对比

| 旧方案（`6.tftp_recovery.py`） | 新方案（`tftp_server.py`） |
|---|---|
| `subprocess` 调 `in.tftpd` / `dnsmasq` | 纯 Python `socket` |
| 需要 `sudo apt install dnsmasq` | 零系统依赖 |
| 步骤脚本退出后 TFTP 可能停止 | 独立运行，常驻 |
| 写死 `/srv/tftp` 等根目录 | 默认 `service/tftp/files/`，`--root` 可配 |
| 单次流程控制 | 任意次传输，不限客户端数 |
| 无后台模式 | `--daemon` 守护化 |

## 验证

```bash
# 服务器启动
python3 tftp_server.py --port 9999 --debug &

# 客户端下载（tftp 或 busybox tftp）
printf "get initramfs-recovery.itb\nquit\n" | tftp 127.0.0.1 9999

# 重复测试（确认常驻）
printf "get sysupgrade.itb\nquit\n" | tftp 127.0.0.1 9999
```

## 已知限制

- **只读**：不支持 WRQ（写请求），刷机场景不需要
- **端口 69 需要 root**：`--port` 可绕开
- **无 log 持久化**：stderr 日志是 stdout 通道，服务器化后建议 `--daemon` + shell 重定向
