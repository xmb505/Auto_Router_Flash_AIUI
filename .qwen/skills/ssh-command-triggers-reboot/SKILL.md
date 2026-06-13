---
name: ssh-command-triggers-reboot
description: 通过 SSH 触发路由器/嵌入式设备重启命令（sysupgrade/reboot）后，SSH 连接被远端关闭是预期成功，不要用 exit code 判断成败
source: auto-skill
extracted_at: '2026-06-11T15:03:01.813Z'
---

# SSH 触发设备重启后连接关闭的处理模式

## 适用场景

通过 SSH（sshpass）登录设备并运行会触发设备重启的命令，例如：

- `sysupgrade -F /tmp/initramfs-kernel.bin` — 刷固件后路由器 reboots
- `reboot` / `shutdown -r now` — 显式重启
- `mtd write ...; reboot` — 写 flash 后立即重启

设备重启后，SSH 服务端关闭所有 shell session → sshpass 收到 broken pipe / connection reset → exit code 非 0（如 255）。

## 核心问题

sshpass 返回非 0 exit code，但命令实际上是成功的。**不能**靠 `result.returncode == 0` 判断，也不能靠 `miwifi_ssh.sh` 等封装脚本的 JSON `.ok` 字段。

## 正确做法

**检查 stdout + stderr 的输出内容**，寻找命令成功的文本标志。

**关键陷阱**：`"Connection ... closed by remote host"` 报文由 SSH 客户端发出，经 sshpass 传递，**不一定被 subprocess `capture_output` 捕获**（可能走不同的 stderr 通道或直接被吞）。因此**不依赖它做判断**。

```python
combined = f"{result.stdout}\n{result.stderr}"
# ✅ "Commencing upgrade" 由远程路由器发出（sysupgrade 进程的 stdout），
#    在 subprocess 中总是可靠捕获。只要看到它，sysupgrade 一定触发了。
# ❌ 不依赖 "closed by remote host"——该报文在 sshpass+subprocess 链路中可能丢失。
is_success = "Commencing upgrade" in combined
```

## 生产环境代码模式

```python
import subprocess

def ssh_trigger_reboot(ip, user, pwd, cmd, timeout=60):
    """SSH 执行会触发设备重启的命令。连接被远端关闭视为成功。"""
    result = subprocess.run(
        [
            "sshpass", "-p", pwd, "ssh",
            "-oStrictHostKeyChecking=no",
            "-oUserKnownHostsFile=/dev/null",
            "-oLogLevel=ERROR",
            f"{user}@{ip}", cmd,
        ],
        capture_output=True, text=True, timeout=timeout,
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    combined = f"{out}\n{err}"

    # 成功标志：命令相关的完成文本 —— 不依赖 "closed by remote host"
    # 因为该报文在 sshpass + subprocess 链路中可能丢失（exit code 会反映断开）
    is_success = "Commencing upgrade" in combined

    if is_success:
        return {"ok": True, "stdout": out, "stderr": err}

    raise RuntimeError(
        f"命令失败 (exit={result.returncode}): {out} {err}".strip()
    )
```

## 注意

- **不**该通过 miwifi_ssh.sh 等 JSON 封装转发——那些封装依赖 exit code 判 ok，正好在这个场景下失效
- **直接**用 raw sshpass（如上代码段）并捕获 stdout/stderr 原始输出
- 不同命令有不同的成功文本标志，需要**实机验证确认识别**。例如 sysupgrade 是 `"Commencing upgrade"`，reboot 则可能是返回空但 exit code 255——此时可降级为"exit ≠ 0 但在预期时间内断开"
- timeout 设得比默认长（本例用了 60s），因为固件刷写/重启需要时间
