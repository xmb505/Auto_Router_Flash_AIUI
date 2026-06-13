---
name: alpine-container-scp-sftp-workaround
description: Alpine/proot LXC 容器缺少 sftp-server 时，用 scp -O 强制 legacy SCP 协议传输文件
source: auto-skill
extracted_at: '2026-06-12T09:58:29.268Z'
---

# Alpine LXC 容器 SCP/SFTP 传输文件解决步骤

## 问题

向 Alpine Linux LXC 容器做 `scp` 时报错：

```
sh: /usr/lib/ssh/sftp-server: not found
scp: Connection closed
```

原因是 Alpine 容器默认**不带** OpenSSH 的 `sftp-server` 子系统，而现代 `scp` 客户端
默认使用 SFTP 协议传输（而非 legacy SCP 协议），SFTP 握手需要 `sftp-server` 在远程端。

## 解决

使用 `scp -O` 强制走 legacy SCP 协议，绕过 SFTP 子系统的依赖：

```bash
sshpass -p '<password>' scp -O -o StrictHostKeyChecking=no \
  root@<container-ip>:/remote/path/file.bin \
  /local/path/
```

### 关键参数

| 参数 | 作用 |
|------|------|
| `-O` | 使用 legacy SCP 协议（OpenSSH 9.0+ 需要显式指定） |
| `-o StrictHostKeyChecking=no` | 首次连接跳过 host key 检查 |

## 备选方案（如果 SCP 都不可用）

通过 PVE 宿主机做管道传输：

```bash
# 从容器 → 本地（经 PVE 宿主机）
sshpass -p '<pve-pwd>' ssh root@pve-host 'cat /var/lib/lxc/<vmid>/rootfs/remote/path/file.bin' > /local/path/file.bin

# 本地 → 容器（经 PVE 宿主机）
cat /local/path/file.bin | sshpass -p '<pve-pwd>' ssh root@pve-host 'tee /var/lib/lxc/<vmid>/rootfs/remote/path/file.bin'
```

但需要知道 LXC rootfs 在 PVE 宿主机上的物理路径（通常是 `/var/lib/lxc/<vmid>/rootfs/`）。

## 原理

- OpenSSH 9.0+（2022 年）默认将 `scp` 的传输层从 legacy SCP 切换为 SFTP，
  以利用 SFTP 更好的错误处理和进度报告。
- Alpine 最小化镜像为缩减体积，**不包含** `openssh-sftp-server` 包。
- `scp -O` 恢复为传统的 `rcp-over-ssh` 管道协议，只依赖 `ssh` 和 remote shell，
  不依赖 SFTP 子系统。
