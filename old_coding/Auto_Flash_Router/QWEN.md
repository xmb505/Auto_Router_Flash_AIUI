# Auto Flash Router

小米/红米路由器自动刷机工具集。覆盖多机型从出厂初始化到刷入 OpenWRT 的完整自动化流程。

## 项目结构

```
Auto_Flash_Router/
├── AX3000T/         # 小米 AX3000T (RD03, MediaTek Filogic 820)
├── AX3600/          # 小米 AX3600 (R3600, Qualcomm IPQ8071A)
├── AX5/             # 红米 AX5 (RA67/RM1800, Qualcomm IPQ6000)
├── HTTPSERVER/      # HTTP 文件服务器 + unlock_ssh.sh
├── xmir-patcher/    # 第三方固件补丁工具 (git submodule)
└── QWEN.md          # 本文件
```

## 支持机型

| 目录 | 型号 | SoC | 漏洞 | SSH 方式 | uboot |
|------|------|-----|------|----------|-------|
| AX3000T | 小米 AX3000T (RD03) | IPQ5000 (MediaTek) | `start_binding` 注入 | 秒级，无需重启 | FIP (mtd5) |
| AX3600 | 小米 AX3600 (R3600) | IPQ8071A (Qualcomm) | `set_config_iotdev` 注入 | 秒级，无需重启 | APPSBL (mtd7) |
| AX5 | 红米 AX5 (RA67) | IPQ6000 (Qualcomm) | `set_config_iotdev` 注入 | 需重启 | APPSBL (mtd7) |

## 通用刷机流程

所有机型遵循相似的流水线：

```
出厂检测 → 初始化 → 降级(如需) → 开SSH → 刷过渡固件
  → 刷MIBIB+uboot → 断电重启 → uboot web上传最终固件
```

### 阶段详解

| 阶段 | AX3000T | AX3600 | AX5 |
|------|---------|--------|-----|
| **初始化** | `newEncryptMode=1` (SHA256) | `newEncryptMode=0` (SHA1) | `newEncryptMode=0` (SHA1) |
| **降级** | 1.0.47 | 1.0.17 | 1.0.26 |
| **SSH 注入** | `start_binding` API, `\n` 分隔 | `set_config_iotdev` API, `;` 分隔 | `set_config_iotdev` API, 下载脚本 |
| **uboot 分区** | mtd5 (FIP) | mtd7 (APPSBL) | mtd7 (APPSBL) |
| **最终固件** | sysupgrade (initramfs→sysupgrade) | factory UBI (一次性) | factory UBI (一次性) |

## 各机型详情

### AX3000T → `AX3000T/QWEN.md`

- **加密**: `newEncryptMode=1`, SHA256 双哈希
- **漏洞**: `start_binding` API 的 `key` 参数注入；`;` 被过滤，用 `\n` 绕过
- **SSH**: root/root，秒级就绪
- **uboot**: FIP 格式，刷入 mtd5
- **TFTP**: 自带 `tftpd.py` 最小 TFTP 服务器
- **sysupgrade**: 先刷 initramfs，再 sysupgrade -F

### AX3600 → `AX3600/QWEN.md`

- **加密**: `newEncryptMode=0`, SHA1 双哈希
- **版本自适应**: 1.0.x 跳过 `bw160`；1.1.x+ 包含 `bw160=false`
- **漏洞**: `set_config_iotdev` API 的 `ssid` 参数注入；`;` 可用
- **SSH**: root/root，4条命令注入，秒级就绪
- **双固件**: rootfs (mtd12) + rootfs_1 (mtd13)，`flag_boot_rootfs` 切换
- **uboot**: APPSBL (mtd7)，`pepe2k/u-boot_mod v21.12.26`
- **最终固件**: factory UBI 文件，通过 uboot web 上传，一次性到位

### AX5 → `AX5/QWEN.md`

- **加密**: `newEncryptMode=0`, SHA1 双哈希
- **漏洞**: `set_config_iotdev` API 注入，远程下载 `unlock_ssh.sh`
- **SSH**: root/password，需重启
- **uboot**: APPSBL (mtd7)，需同时设置 nvram bootcmd
- **MIBIB**: 分区表必须通过 uboot web 刷（系统内锁定）

## 共享工具

### HTTPSERVER/

```
HTTPSERVER/
├── chfs              # 迷你 HTTP 文件服务器 (CuteHttpFileServer)
└── unlock_ssh.sh     # AX5 SSH 解锁脚本（通过 HTTP 下载到路由器执行）
```

### xmir-patcher/

第三方固件补丁工具集（git submodule），支持多种小米路由器固件的解包、修改、打包。

```bash
cd xmir-patcher
bash run.sh          # Linux/macOS
# 或
run.bat              # Windows
```

## 密码学基础

所有小米路由器共享相同的加密常量和核心算法。

### 常量

| 常量 | 值 |
|------|-----|
| KEY | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| IV | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |

### 算法对比

| 算法 | AX3000T (newEncryptMode=1) | AX3600/AX5 (newEncryptMode=0) |
|------|---------------------------|-------------------------------|
| 登录哈希 | SHA256(nonce + SHA256(pwd+KEY)) | SHA1(nonce + SHA1(pwd+KEY)) |
| 登录方式 | POST 表单 | GET 参数 |
| oldPwd | SHA256(nonce + SHA256(pwd+KEY)) | SHA1(nonce + SHA1(pwd+KEY)) |
| newPwd key | SHA256(oldPwd+KEY)[:32] | SHA1(oldPwd+KEY)[:32] |
| newPwd256 | SHA256-AES (额外字段) | 无 |
| nonce 格式 | `0__{ts}_{rand}` | `0__{ts}_{rand}` |

### 注入方式对比

| 特性 | AX3000T (start_binding) | AX3600/AX5 (set_config_iotdev) |
|------|------------------------|-------------------------------|
| API | `/api/xqsystem/start_binding` | `/api/misystem/set_config_iotdev` |
| 参数 | `key` | `ssid` |
| 分隔符 | `\n` (; 被过滤) | `;` (可用) |
| 前缀 | `1234' -X \n` | `-h;` |
| 是否需要 HTTP 服务器 | 否 | AX5 需要 (curl 下载脚本) |

## 脚本约定

- **JSON 输出** — 所有 Python 脚本 stdout 输出纯 JSON，stderr 输出进度
- **出错退出码** — 失败 exit 1，成功 exit 0
- **argparse** — 所有 Python 脚本支持 `--help`
- **依赖** — `auto_init.py` 需 `pycryptodome`；SSH/SCP 脚本需 `sshpass`；其余纯标准库
- **SSH 连接** — 路由器只提供 `ssh-rsa` host key，连接时需 `-oHostKeyAlgorithms=+ssh-rsa`

## Git

- **仓库**: git@github.com:xmb505/Auto_Flash_Router.git
- **分支**: master
- **提交规范**: 简短描述改动内容

## 内存系统

项目上下文缓存在 `.qwen/projects/-home-xmb505-Auto-Flash-Router/memory/MEMORY.md`，包含各机型的详细技术发现和调试记录。
