# Newifi D2（新路由3）— 刷机流水线

> MT7621A / 512MB DDR3 / 32MB SPI NOR Flash

## 流水线一览

```
状态检测 → 开SSH → 注入breed → breed刷initramfs → sysupgrade
```

## 一键编排

> 子脚本本来就能独立跑，编排脚本就是把现有脚本串起来、传参数、拿 JSON 结果。

| 场景 | 脚本 | 子流程 | 需要 sudo |
|------|------|--------|----------|
| **stock → OpenWrt 端到端** | `all_official_2_openwrt.py` | `all_official_2_breed` → `all_breed_auto_flash` | ✅（breed 探测） |
| stock → breed 注入 | `all_official_2_breed.py` | `check_init` → `login_get_sid` → `ssh_enable` → `breed_inject` | ❌ |
| breed → OpenWrt | `all_breed_auto_flash.py` + `all_breed_auto_flash.ini` | `breed_enter` → `breed_flash` → `ping/ssh/sysupgrade` | ✅（breed 探测） |

### 端到端一键刷机

```bash
# 1. 填 INI（固件名 + 网卡）
$EDITOR all_breed_auto_flash.ini

# 2. 断电待上电，然后运行
sudo python3 all_official_2_openwrt.py --debug
```

CLI 参数：

| 脚本 | 参数 | 说明 |
|------|------|------|
| `all_official_2_openwrt.py` | `--pwd <密码>` | 路由器管理密码（不传 → check_init 探测，默认 admin）|
| | `--config <ini>` | `all_breed_auto_flash.ini` 路径（默认同目录）|
| | `--debug` | 透传子脚本，打印进度到 stderr |
| `all_official_2_breed.py` | `--pwd <密码>` | 同上 |
| | `--debug` | 透传子脚本 |
| `all_breed_auto_flash.py` | `--config <ini>` | INI 路径（默认同目录）|
| | `--debug` | 透传子脚本 |

### INI 配置示例

```ini
[network]
iface = enp1s0

[firmware]
initramfs_file = files/immortalwrt-25.12.0-ramips-mt7621-d-team_newifi-d2-initramfs-kernel.bin
sysupgrade_file = files/immortalwrt-ramips-mt7621-d-team_newifi-d2-squashfs-sysupgrade.bin

[ssh]
password =
```

> 全部架构约束：subprocess 调用子脚本、解析 JSON stdout、不做 import。

## 步骤脚本

| # | 脚本 | 功能 | 前置 | 实机验证 |
|---|------|------|------|---------|
| — | `check_init.py` | 探测 guide_status（无需密码） | HTTP 可达 | ✅ |
| 2 | `2.login_get_sid.py` | 登录获取 ubus_rpc_session | 已初始化 + 密码 | ✅ |
| 3 | `3.ssh_enable.py` | 调用 xapi.basic.open_dropbear 开启 SSH | sid | ✅ |
| 4 | `4.breed_inject.py` | SCP 上传 .ko + insmod 自动写 breed | SSH 已开 + 密码 | ✅ |
| 5 | `5.breed_flash_firmware.py` | breed Web 上传 + 刷写 initramfs | breed 模式 | ✅ |
| — | `breed_enter.py` | UDP BREED:ABORT 中断进 breed | 已断电待上电 | ✅ |
| — | `router_lecoo_recovery.py` | 恢复出厂设置 | sid | ✅ |
| — | `openwrt_modern_standard_ssh.sh` | SSH 连接辅助 | OpenWrt 已运行 | ✅ |

辅助脚本：

| 脚本 | 功能 |
|------|------|
| `lenovo_lecoo_api.py` | 探测 ubus 公开 API（无需密码） |
| `1.lecco_init.py` | 恢复出厂后首次设置密码（guide_status 0→1）|

## 完整流程

### 1. 检查路由器状态

```bash
python3 check_init.py
```

输出 `is_inited` + `guide_status`：

| guide_status | 含义 | 下一步 |
|-------------|------|--------|
| 0 | 未初始化（出厂默认密码可用） | 直接 `2.login_get_sid --pwd admin` |
| 1 | 已初始化（密码已被修改） | 走 `2.login_get_sid --pwd <已知密码>` |

### 2. 登录获取 sid

```bash
python3 2.login_get_sid.py --pwd <密码>
# → {"ok":true, "data":{"sid":"32位hex", "expires":300}}
```

- 用户名固定 `root`（前端硬编码）
- 密码自动 base64 编码
- sid 有效期 300 秒

### 3. 开启 SSH

```bash
python3 3.ssh_enable.py --sid <sid>
# → SSH 端口 22 开放
```

调用 `xapi.basic.open_dropbear`。SSH 密码同 Web 管理密码。

### 4. 注入 breed

```bash
python3 4.breed_inject.py --pwd <管理密码>
# → SCP → insmod → breed 写入 Flash
```

自动完成：
1. SCP 上传 `newifi-d2-jail-break.ko` 到 `/tmp/`
2. SSH `insmod /tmp/newifi-d2-jail-break.ko`
3. batch 写入 breed 到 Flash，路由器重启

**注意**：需要 `sshpass` 和 `scp -O`（路由器 dropbear 无 sftp-server）。

### 5. 进入 breed 模式

方式一：**物理 Reset 键**
- 断电 → 按住 Reset → 上电 → 5 秒后松开 → breed 模式（192.168.1.1）

方式二：**UDP 中断**（`breed_enter.py`）
- 本机 IP 设为 192.168.1.x/24
- 路由器断电待上电
- 运行 `python3 breed_enter.py` 后立即给路由器上电
- 等待 UDP 响应 "BREED:ABORTED"（约 21s）

### 6. breed 刷写 initramfs

```bash
python3 5.breed_flash_firmware.py --file files/<initramfs-kernel.bin>
```

breed 只能刷 initramfs-kernel.bin（裸 kernel），**严禁刷 sysupgrade**。

刷写过程：
1. `POST /upload.html` 上传固件
2. `GET /upgrading.html` 触发刷写
3. `POST /upgrade_query.html` 轮询进度（约 40s）
4. 100% 后路由器自动重启

### 7. SSH 进 initramfs → sysupgrade

initramfs 启动后（约 25s），SSH 无密码登录：

```bash
# 传 sysupgrade 固件
sshpass -p "" scp -O files/<sysupgrade.bin> root@192.168.1.1:/tmp/firmware.bin

# 执行刷写
sshpass -p "" ssh root@192.168.1.1 "sysupgrade -n /tmp/firmware.bin"
# → SSH 断连（预期成功）
```

### 8. 验证

等待路由器重启完成（约 90s），SSH 登录验证：

```bash
ssh root@192.168.1.1
cat /etc/openwrt_release
```

## API 体系（联想 Lecoo / 官方新路由 stock 固件）

| 项目 | 说明 |
|------|------|
| 协议 | JSON-RPC 2.0 over HTTP POST `/ubus` |
| 登录 | `session.xapi_login`，用户名 `root`，密码 base64 |
| Token | `ubus_rpc_session`（32 位 hex，300s 过期） |
| 权限 | `params[0]` 传 sid，`params[1..3]` 为 object/method/args |

**常用 ubus API：**

| 操作 | 调用 | 无需认证 |
|------|------|---------|
| 固件版本 | `xapi.basic.get_version` | ✅ |
| 探测状态 | `xapi.basic.get_guide_status` | ✅ |
| 开 SSH | `xapi.basic.open_dropbear` | ❌ |
| 重启 | `xapi.system.reboot` | ❌ |
| 恢复出厂 | `xapi.basic.reset_start` | ❌ |
| 改密码 | `xapi.sys.set_login_passwd_base64(old,new,confirm)` | ❌ |
| 查系统 | `system.board` / `system.info` | ❌ |

## 已知固件

| 固件 | 适用 | 文件 |
|------|------|------|
| **ImmortalWrt 25.12.0-rc2** | ✅ 实机验证 | `immortalwrt-ramips-mt7621-d-team_newifi-d2-squashfs-sysupgrade.bin` |
| OpenWrt 25.12.4 | initramfs 已验证 | `openwrt-25.12.4-ramips-mt7621-d-team_newifi-d2-initramfs-kernel.bin` |
| 联想 Lecoo 官方 | 版本 3.2.1.7437 beta (`newifi-d2l`) | 出厂预装 |
| 新路由官方 | 版本 3.2.1.7400 beta (`newifi-d2`) | 出厂预装 |

## Troubleshooting

参见 `troubleshooting.md`。
