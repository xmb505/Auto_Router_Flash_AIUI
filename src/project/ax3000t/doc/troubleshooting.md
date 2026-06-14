# AX3000T 错误排错索引 (Troubleshooting)

脚本出错时 `reason` 字段对应本文件的条目索引。
AI 通过 `reason` 查表定位恢复步骤。

## [stok_expired]

**触发条件**: stok 令牌过期或失效
**recoverable**: true

**恢复步骤**:
1. 重新运行 `2.login_get_stok.py --pwd <密码>`
2. 如果 `1.official_init.py` 刚跑完，stok 因改密已失效 — 这是预期行为，必须重新登录
3. 如果降级后（`3.downgrade.py`），NVRAM 被清，密码回到 admin — 用 `--pwd admin` 登录

## [not_inited]

**触发条件**: 路由器出厂未初始化（`inited=0`）
**recoverable**: true

**恢复步骤**:
1. 运行 `1.official_init.py --admin-pwd <新密码>`
2. 用新密码跑 `2.login_get_stok.py`

## [already_inited]

**触发条件**: 路由器已初始化，尝试再次初始化
**recoverable**: true

**恢复步骤**:
1. 跳过 `1.official_init.py`
2. 直接 `2.login_get_stok.py --pwd <已知密码>`
3. 如果不知道密码，需恢复出厂或按 Reset 按钮

## [auth_failed]

**触发条件**: 密码错误导致登录失败
**recoverable**: true

**恢复步骤**:
1. 确认密码正确（初始化时设的密码）
2. 如果不确定，尝试 `admin`（出厂默认）或 `12345678`（常用测试密码）
3. 如果都不行，需物理 Reset 恢复出厂

## [network_unreachable]

**触发条件**: 路由器不可达（curl/SSH 超时）
**recoverable**: true

**恢复步骤**:
1. 检查网线/WiFi 连接
2. 确认 IP 正确:
   - stock 固件阶段: `192.168.31.1`
   - uboot/TFTP 阶段: `192.168.1.1`（路由器）/ `192.168.1.254`（主机 TFTP）
   - OpenWrt 阶段: `192.168.1.1`
3. 路由器可能正在重启，等待 1-2 分钟后重试

## [firmware_rejected]

**触发条件**: 固件上传/刷写被路由器拒绝
**recoverable**: false

**排查**:
1. 确认固件文件正确:
   - 降级: `RD03_1.0.47.bin`（AX3000T 专用）
   - uboot: `immortalwrt-...-bl31-uboot.fip`
   - initramfs: `immortalwrt-...-initramfs-recovery.itb`
   - sysupgrade: `immortalwrt-...-squashfs-sysupgrade.itb`
2. 不要混用 AX5/AX6 的固件文件
3. `flash_rom` 报 `code:1532` = 固件签名不对

## [ssh_failed]

**触发条件**: SSH 连接失败
**recoverable**: true

**恢复步骤**:
1. 确认 SSH 已启用（步骤 4 成功）
2. 密码: `root`（注入时设定的）
3. 需要 `+ssh-rsa` host key 算法:
   ```bash
   sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
   ```
4. 如果 dropbear 未启动，重新跑 `4.enable_ssh.py`

## [mtd_write_failed]

**触发条件**: MTD 写入失败
**recoverable**: false

**排查**:
1. 确认目标 mtd 正确: FIP 分区 (mtd5)
2. 确认文件已上传到 `/tmp/`: `ls -la /tmp/uboot.fip`
3. 手动验证: `ssh mtd write /tmp/uboot.fip FIP`

## [file_not_found]

**触发条件**: 固件文件不存在
**recoverable**: true

**恢复步骤**:
1. 检查 `files/` 目录下的文件是否存在
2. 确认路径正确（相对路径 vs 绝对路径）

## [start_binding_blocked]

**触发条件**: `start_binding` 注入被新固件修补
**recoverable**: true

**恢复步骤**:
1. 降级到 `1.0.47` 固件: `3.downgrade.py --file files/RD03_1.0.47.bin`
2. 降级后 NVRAM 被清，重跑步骤 1+2
3. 再跑 `4.enable_ssh.py`

## [tftp_server_unavailable]

**触发条件**: 主机未安装或无法启动 TFTP 服务器
**recoverable**: true

**恢复步骤**:
1. 安装 TFTP 服务器: `sudo apt install dnsmasq` 或 `sudo apt install atftpd`
2. 确认端口 69 未被占用: `ss -ulnp | grep ':69'`
3. 手动测试: `sudo dnsmasq --port=0 --enable-tftp --tftp-root=/tmp/tftpboot --no-daemon`

## [no_network_interface]

**触发条件**: 未找到可配置为 192.168.1.x 的网卡
**recoverable**: true

**恢复步骤**:
1. 查看网卡列表: `ip link show`
2. 手动配置: `sudo ip addr add 192.168.1.254/24 dev <网卡名>`
3. 用 `--iface <网卡名>` 参数指定

## [tftp_recovery_failed]

**触发条件**: uboot 未成功拉取 recovery 镜像
**recoverable**: true

**恢复步骤**:
1. 确认 TFTP 服务器运行: `ss -ulnp | grep ':69'`
2. 确认主机 IP 为 192.168.1.254: `ip addr show`
3. 确认 recovery 文件在 TFTP 根目录: `ls /srv/tftp/` 或 `ls /tmp/tftpboot/`
4. 检查网线连接（路由器 LAN 口 ↔ 主机网口）
5. 物理断电重启路由器

## 通用排错流程

```
1. 查看脚本 stderr: 加 --debug 重跑
2. 查看 JSON 输出: ok=false 时读 error + reason 字段
3. 在本文件找 [reason] 条目
4. 按恢复步骤操作
5. 如果仍失败，检查 flash-pipeline.md 确认当前在正确阶段
```
