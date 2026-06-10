# Router Flash Tool

路由器批量刷机工具，支持 CR660X 和 JGC-Q10/Qx 系列路由器。

## 功能特性

- **CR660X 刷机**：支持官方系统破解、uboot 刷入、OpenWRT 升级
- **JGC 刷机**：三阶段刷机流程（官方→PDCN→Bootloader→最终系统）
- **TUI 界面**：交互式刷机流程，中文界面
- **批量刷机**：自动记录刷机数量和 MAC 地址

## 系统要求

- Alpine Linux（LXC 容器）
- Python 3
- 网络连接到路由器所在网段

## 安装依赖

```bash
# Alpine Linux
apk add ping sshpass openssh-client python3 py3-pip

# Python 包
pip install requests rich scapy
```

## 快速开始

```bash
cd src
python3 main.py
```

## 网络配置

确保容器与路由器在同一二层网络，配置 `sysctl`：

```bash
sysctl -w net.ipv4.conf.all.rp_filter=2
```

可选（加快 ARP 缓存刷新，在 PVE 宿主机配置）：

```bash
# /etc/sysctl.conf
net.ipv4.neigh.default.base_reachable_time_ms = 5000
net.ipv4.neigh.default.gc_stale_time = 5
net.ipv4.neigh.default.retrans_time_ms = 500
sysctl -p
```

## 配置

编辑 `src/config.yaml`：

```yaml
cr660x:
  detect_ips:
    - "10.11.12.1"   # 最终系统
    - "192.168.1.1"  # uboot/initramfs
    - "192.168.10.1"  # 移动默认
  final_ip: "10.11.12.1"

jgc:
  detect_ips:
    official: "192.168.10.1"
    pdcn: "192.168.123.1"
    uboot: "192.168.1.1"
    final: "10.11.12.1"
```

## 使用说明

### CR660X 刷机

1. **官方系统破解**：输入 8 位路由器密码，自动执行 Stage 1 + Stage 2
2. **OpenWRT 升级**：仅执行 Stage 2（适用于已有 initramfs 的路由器）
3. **UBOOT 上传 KERNEL**：从 uboot 状态刷入 kernel，自动进入 Stage 2

### JGC 刷机

1. **步骤 1**：官方系统 → PDCN
2. **步骤 2**：PDCN → Bootloader
3. **步骤 3**：Bootloader → 最终系统

可在任意步骤开始，程序会自动执行后续步骤。

### 快捷键

- `r`：重新检测 IP
- `q`：返回上级菜单

## 目录结构

```
src/
├── main.py              # TUI 主程序
├── config.py            # 配置加载
├── config.yaml          # 配置文件
├── utils.py             # 网络工具
├── cr660x/
│   └── flasher.py      # CR660X 刷机模块
├── jgc/
│   └── flasher.py      # JGC 刷机模块
└── firmware/
    ├── cr660x/         # CR660X 固件
    └── jgc/            # JGC 固件 + chfs
```

## 固件文件

- `pb-boot.img`：Bootloader
- `sharewifi_initramfs-kernel.bin`：Initramfs 内核
- `sharewifi_1.0.7.bin`：CR660X 最终固件
- `JCG-Q20-PDCN.bin`：JGC PDCN 固件
- `sharewifi_jqg_q20_1.1.bin`：JGC 最终固件
