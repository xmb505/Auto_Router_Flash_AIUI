# Newifi D2 — 刷机流水线

> Newifi D2 (MT7621) 不是小米路由器，没有 Xiaomi 加密/API 体系。刷机方式取决于当前运行状态。

## 状态机

```
新路由器 (无系统 / breed 模式)
    → breed Web (192.168.1.1) 上传固件
    → 刷机完成

已运行 OpenWrt (SSH 可连)
    → SSH 上传 sysupgrade 固件
    → sysupgrade 刷写
    → 刷机完成

已运行 Padavan
    → SSH 上传固件
    → mtd_write 刷 firmware 分区
    → 刷机完成
```

## 步骤脚本

| # | 脚本 | 功能 | 前置 | 状态 |
|---|------|------|------|------|
| 1 | `breed_enter.py` | 广播 BREED:ABORT 中断启动进入 breed | 路由器**已断电待上电** | ✅ 实测通过 |
| 2 | `breed_flash.py` | POST `/upload.html` 上传 + POST 轮询 `/upgrade_query.html` | breed 已激活 | 规划中（curl 手动验证过协议，脚本文件未创建） |
| 3 | `check_state.py` | 探测当前在 OpenWrt / breed / Padavan | 无 | 规划中 |
| 4 | `ssh_sysupgrade.py` | 通过 SSH 执行 sysupgrade | OpenWrt 已运行 | 规划中 |

## 决策树

```
                        [路由器状态?]
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
           breed           OpenWrt          Padavan
              │               │               │
   breed_flash.py       ssh_sysupgrade.py   ssh_mtd_write.py
              │               │               │
              └───────────────┴───────────────┘
                              ▼
                          [刷机完成]
```

## Breed Web API（实测 2026-06-10）

进入 breed 模式后，Web 服务在 `http://192.168.1.1/` 提供以下端点：

### 上传：`POST /upload.html` (multipart/form-data)

**两种模式**：

| 模式 | `fw_type` | 适用 |
|------|-----------|------|
| 常规固件 | `generic` | **initramfs-kernel.bin**（裸 kernel+initrd 镜像） |
| 编程器固件 | `fullflash` | 完整 32MB flash dump |

**⚠️ breed 严禁刷入 sysupgrade 固件！** Sysupgrade 是 OpenWrt 专有格式（含 metadata 头/签名），breed 不识别也不应尝试。Breed 只接受**裸 firmware 镜像**（initramfs-kernel 或编程器固件）。

**刷 sysupgrade 的正确路径**：
1. 在 breed 里**刷 initramfs-kernel.bin** → 启动到 initramfs 系统
2. 在 initramfs shell 里 `scp` 上传 sysupgrade.bin
3. 在 initramfs shell 里跑 `sysupgrade -n <file>` → 写持久 rootfs + 自动重启

**generic 模式字段**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `fw_type` | ✅ | 固定 `generic` |
| `fw_file` | ✅ | **initramfs-kernel.bin**（裸 firmware 镜像） |
| `fw_check` | ✅ | `=1` 才会上传 fw_file |
| `flash_layout` | ✅ | D2 选 `reference` (kernel @ 0x50000) |
| `submit` | ✅ | 固定 `Upload` |
| `boot_file` + `boot_check` | ❌ | 同步刷 bootloader 时用 |
| `eeprom_file` + `eeprom_check` | ❌ | 同步刷 Wi-Fi 校准时用 |

**fullflash 模式字段**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `fw_type` | ✅ | 固定 `fullflash` |
| `fullflash_file` | ✅ | 完整 32MB flash dump |
| `fullflash_check` | ✅ | `=1` |
| `submit` | ✅ | `Upload` |

**Flash 布局选项**（`flash_layout`）：

| 值 | 含义 | 适用 |
|----|------|------|
| `reference` | kernel @ 0x50000 | **D2 默认** |
| `compact` | kernel @ 0x40000 | |
| `big` | kernel @ 0x60000 | |
| `phicomm` | kernel @ 0xA0000 | 斐讯 |
| `wndr3700v5` | 特殊布局 | Netgear |

### 实际刷写流程（用户抓包确认，2026-06-10）

```bash
# 1) 上传固件（响应是确认页，含文件名/大小/MD5）
POST /upload.html
  Content-Type: multipart/form-data
  boot_file=                     # 浏览器会发空字段
  fw_check=1
  fw_file=@<固件>
  flash_layout=reference
  fw_type=generic
  submit=Upload
  → 响应: has_fw=1, 4257 字节 HTML 确认页

# 2) 浏览器点"更新"按钮 → 加载轮询页（同时触发实际刷写！）
GET /upgrading.html
  → 响应: 2802 字节 HTML 含 ajax.js 引用
  ★ 这个 GET 才是"开始刷写"的触发点，不是 upload 也不是 POST
  → 之后 ajax.js 自动 POST 轮询 /upgrade_query.html

# 3) JS 自动 POST 轮询（每秒一次）
POST /upgrade_query.html
  Content-Type: application/x-www-form-urlencoded
  Body: ""
  → 响应: 纯数字（当前进度 %）

# 4) 数字到 100 → 触发 reboot
# 两种方式（任选）：
#   a) breed 状态机自动 reboot（实测有时生效有时不生效）
#   b) 手动：先 GET /reboot.html 拿动态 magic, 再 POST /rebooting.html
GET /reboot.html
  → 响应 HTML 含 <input name="magic" value="<动态值>">
  ★ magic 每次 session 都不同！从 HTML 提取后立即使用

POST /rebooting.html
  Content-Type: multipart/form-data
  submit=Reboot
  magic=<从 /reboot.html 抓的值>
  → 响应: 302 → /

# 5) 等待 30~90s 看重启
#    成功信号: Server header 从 "Breed/1.0" 变成 uhttpd（无 Server 字段）
#    /cgi-bin/luci 返回 403 + x-luci-login-required
```

**⚠️ 关键陷阱**：
- `/upgrade_query.html` 必须用 **POST**，用 GET 也能拿到数字但**不会触发 100% 后的 reboot 状态机**
- `magic` 是**动态生成**的，每次 `GET /reboot.html` 都不一样。HTML 里写死某个值是误导——必须**先 GET 再 POST**

### 下载：`GET /backup.html?type=<type>`

| type | 内容 |
|------|------|
| `eeprom` | Wi-Fi 校准 (factory 分区, 64K) |
| `full` | 完整 32MB flash dump |
| `firmware` | ❌ 注释掉，不可用 |

### 其他端点

| 端点 | 功能 |
|------|------|
| `GET /index.html` | 系统信息（CPU/RAM/Flash/频率） |
| `GET /clock.html` | CPU/DDR 频率设置 |
| `GET /envedit.html` | uboot env 任意读写（默认禁用） |
| `GET /envconf.html` | 预设字段写 env |
| `GET /reboot.html` | 手动重启（一般不用，flash 100% 自动重启） |
| `GET /reset.html` | 恢复出厂 |

## BREED:ABORT 协议（已验证）

**触发**：路由器通电后，breed 在极短时间窗内监听 UDP 37541 端口。

| 方向 | 地址 | 载荷 | 字节 |
|------|------|------|------|
| PC → 路由器 | `255.255.255.255:37541` (广播) | `BREED:ABORT` | 12 |
| 路由器 → PC | `<router_ip>:37540` (单播) | `BREED:ABORTED` | 14 |

**实施参数**：
- 广播间隔：500ms（实测 21s 内约 43 次尝试）
- 监听端口：37540
- Linux 绑定接口：`SO_BINDTODEVICE`（需 `sudo`）
- 默认超时：180s（3 分钟，给手动通电留足时间）
