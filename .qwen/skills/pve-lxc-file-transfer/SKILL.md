---
name: pve-lxc-file-transfer
description: PVE 宿主机下，当 LXC 容器 SSH 不可用（无密码认证、无 sftp-server、dropbear 限制）时，通过 pct exec + tar pipe 实现文件双向传输
source: auto-skill
extracted_at: '2026-06-12T10:12:08.240Z'
---

# PVE LXC 容器文件传输（pct exec + tar pipe）

## 适用场景

PVE 宿主机上的 LXC 容器（特别是 Alpine 最小化镜像）有以下限制：
- 容器内 **dropbear 未开启密码认证**（`Permission denied (publickey,password)`）
- 容器内 **无 sftp-server**（Alpine 最小安装不包含 `openssh-sftp-server`）
- 即使 `scp -O` 可用，有时也需要对整个目录做批量传输

此时 **无法直接从外部 scp/ssh 到容器**，但可以通过 PVE 宿主机上的 `pct exec` 绕过。

## 前置条件

- 有 PVE 宿主机 root SSH 权限
- 目标 LXC 容器在运行中（`pct status <vmid>` 为 running）

## 方法：tar 管道传输

### 从容器 → 本地

```bash
# 容器内 /remote/path/dir → 本地 /local/target/
sshpass -p '<pve-pwd>' ssh root@pve-host \
  'pct exec <vmid> -- tar czf - -C /remote/path dir' \
  | tar xzf - -C /local/target/
```

**参数说明**：
- `tar czf - -C /remote/path dir`：打包 `/remote/path/dir` 目录的内容（`-C` 先切目录，`dir` 是相对路径）
- `| tar xzf - -C /local/target/`：在本地解压到目标目录
- `2>/dev/null` 可选，用于丢弃 stderr 里的 shell 警告

### 本地 → 容器

```bash
# 本地 /local/path/file → 容器 /remote/target/
tar czf - -C /local/path file \
  | sshpass -p '<pve-pwd>' ssh root@pve-host \
    'pct exec <vmid> -- tar xzf - -C /remote/target'
```

### 透传文件而非目录（单文件）

```bash
# 容器 → 本地
sshpass -p '<pve-pwd>' ssh root@pve-host \
  'pct exec <vmid> -- cat /remote/path/file.bin' > /local/path/file.bin

# 本地 → 容器
cat /local/path/file.bin \
  | sshpass -p '<pve-pwd>' ssh root@pve-host \
    'pct exec <vmid> -- tee /remote/path/file.bin > /dev/null'
```

## 备选方案：通过 PVE 文件系统直接访问

需要知道 LXC rootfs 在 PVE 宿主机上的物理路径：

```bash
# 常见路径
/var/lib/lxc/<vmid>/rootfs/
# 或
/var/lib/lxc/<vmid>/rootfs/

# 通过 PVE 直接读写
sshpass -p '<pve-pwd>' ssh root@pve-host \
  'cat /var/lib/lxc/<vmid>/rootfs/remote/path/file.bin' > /local/path/file.bin
```

但此路径取决于 PVE 存储配置（local-lvm 的 LVM 卷路径不同），不如 `pct exec` 通用。

## 原理解释

- `pct exec <vmid> -- <cmd>` 在 PVE 宿主机上通过 `lxc-attach` 进入容器命名空间执行命令
- `tar czf -` 将 stdout 作为 tar 输出流（`-f -` 表示输出到 stdout）
- 通过 SSH 管道将 stdout 流透明地传递到本地
- 接收端 `tar xzf -` 从 stdin 读取并解压

此方法不依赖容器内 SSH 服务，不依赖网络可达性，只依赖 PVE 宿主机上有 `pct` 工具。
