# Newifi D2 — 错误排查

## [permission_denied] SO_BINDTODEVICE 失败

**现象**：`breed_enter.py --iface <name>` 报 `OSError: [Errno 1] Operation not permitted`

**原因**：SO_BINDTODEVICE 是 root-only 的 socket 选项（需 CAP_NET_RAW）

**恢复步骤**：
1. 用 `sudo` 运行：`sudo python3 breed_enter.py --iface <name>`
2. 或改用 `--bind-ip <ip>`（不需要 root）

**recoverable**：true
**相关脚本**：breed_enter

## [breed_not_responding] 180s 内未收到 BREED:ABORTED

**现象**：`breed_enter.py` 超时返回，stdout `reason: "breed_not_responding"`

**原因**：
- 路由器未在 180s 内通电（用户忘了插电）
- 网卡绑定错接口（广播没到路由器）
- 路由器**已**在 OpenWrt/Padavan 运行（breed 阶段早已过去）
- 路由器上安装的不是 breed（是官方 uboot）

**实测参考**：正常进入 breed 的响应时间约 **21s**（43 次 × 500ms），所以 180s 默认超时留足 8 倍余量。

**恢复步骤**：
1. 路由器断电 → 重新跑 `breed_enter.py` → 看到 "监听 :37540" 输出 → **再**插电
2. 用 `--iface` 显式绑定到路由器所在网口
3. 用 `curl http://192.168.1.1/` 验证是否能进 breed Web（通了说明成功了）
4. 如果 curl 不通，按 reset 重来

**recoverable**：true
**相关脚本**：breed_enter

## [breed_unreachable] Breed Web 不可达

**现象**：脚本已 `ok: true`，但浏览器 `http://192.168.1.1` 打不开

**原因**：
- 路由器**已自动重启**（breed 默认 30s 后超时无操作会重启）
- 网卡绑定错接口
- 路由器 IP 不是默认 192.168.1.1

**恢复步骤**：
1. 看到 `ok: true` 立刻开浏览器（< 30s）
2. 重新跑 `breed_enter.py`（路由器会再次断电重启）
3. 用 `--open-browser` 让脚本收到响应后自动开浏览器

**recoverable**：true
**相关脚本**：breed_enter, breed_flash

## [wrong_iface] 广播从错误的网卡发出

**现象**：脚本 timeout，但路由器确实已通电

**原因**：默认绑 0.0.0.0 时，广播从所有接口发。如果其他子网有 breed 在监听，会先响应错的那台。

**恢复步骤**：
1. `ip -o -4 addr show` 列出所有接口 IP
2. 找到路由器所在网口对应的 IP
3. 用 `--bind-ip <ip>` 或 `--iface <name>` 显式绑定

**recoverable**：true
**相关脚本**：breed_enter

## [initramfs_wrong_format] ❌ **此条为错，已废弃**

原始错误诊断：initramfs-kernel.bin 不能直接刷。

**正确认知**（2026-06-10 用户纠正）：
- initramfs-kernel.bin **可以**通过 `/upload.html` 刷入 breed（实测成功启动）
- **真正不能刷的是 sysupgrade.bin**（OpenWrt 专有格式，breed 不识别）
- breed 只能刷**裸 kernel 镜像**（initramfs-kernel）或**编程器固件**（fullflash）

**正确的 sysupgrade 流程**：
1. 在 breed 刷 initramfs-kernel.bin → 启动到 initramfs OpenWrt
2. 在 initramfs shell 里 `scp` 上传 squashfs-sysupgrade.bin
3. 跑 `sysupgrade -n <file>` → 写持久 rootfs + 自动重启

**recoverable**：true（用 initramfs 走 sysupgrade 流程）

## [query_should_be_post] 用了 GET /upgrade_query.html 看不到自动重启

**现象**：flash 进度到 100，路由器不自动重启，停在 breed

**原因**：`/upgrade_query.html` 必须用 **POST**（不是 GET）。GET 也能拿到数字，但不会触发 100% 后的 reboot 流程。Breed 的轮询 JS 用 `RequestURL()` 默认走 POST。

**恢复步骤**：
1. 重新跑完整流程，确认用 POST：
   ```bash
   curl -X POST http://192.168.1.1/upgrade_query.html
   ```
2. 等到返回 `100`，breed 自动重启
3. 检测成功信号：Server header 消失 + `/cgi-bin/luci` 返回 403

**recoverable**：true
**相关脚本**：breed_flash

## [stale_magic] reboot POST 用了写死的 magic 值

**现象**：POST `/rebooting.html` 返 302，但路由器不重启；flash 100% 进度完成但 breed 一直不切到新系统

**原因**：`magic` 字段是**动态生成**的——每次 `GET /reboot.html` 都不同。HTML 里的 `<input name="magic" value="139482">` 是**误导性的默认值**，实际值是 server-side 动态算的。

**实测**：
- HTML 静态读出来：`magic=139482`
- Firefox 抓包：`magic=73994`
- 不同 session 值都不同

**恢复步骤**：
1. 每次 reboot 前**先 GET /reboot.html** 重新提取 magic
2. 用提取的值 POST `/rebooting.html`
3. 完整正确流程：
   ```bash
   magic=$(curl -s http://192.168.1.1/reboot.html | grep -oE 'name="magic" value="[0-9]+"' | grep -oE '[0-9]+')
   curl -X POST -F "submit=Reboot" -F "magic=$magic" http://192.168.1.1/rebooting.html
   ```

**recoverable**：true
**相关脚本**：breed_flash

## [ssh_refused] SSH 连接被拒

**现象**：SSH 连接 `192.168.1.1` 返回 Connection refused

**原因**：
- OpenWrt 未启动 dropbear（首次启动需时间）
- Padavan 默认不开 SSH（需在 Web 开启）
- 路由器不在 OpenWrt/Padavan 状态（可能砖了）

**恢复步骤**：
1. 确认路由器供电正常、启动完毕（等待 2 分钟）
2. `ping 192.168.1.1` 检查可达
3. 如果 SSH 仍不可达，尝试 breed 模式
4. 如果 breed 也进不去，考虑编程器恢复

**recoverable**：true
**相关脚本**：check_state, ssh_sysupgrade, ssh_mtd_write

## [sysupgrade_failed] sysupgrade 失败

**现象**：sysupgrade 命令返回错误

**原因**：
- 固件不兼容（架构/型号不匹配）
- Flash 空间不足
- sysupgrade 元数据损坏

**恢复步骤**：
1. 确认固件是 Newifi D2 的 `mipsel_24kc` 架构
2. 尝试 breed Web 模式刷入（最保险）
3. 检查 `/tmp/` 空间：`df -h /tmp`

**recoverable**：true
**相关脚本**：ssh_sysupgrade, breed_flash

## [breed_upload_fail] Breed Web 上传失败

**现象**：Breed Web 页面固件上传报错

**原因**：
- 固件体积超 breed 限制（32MB Flash 上限）
- 固件格式不对（breed 只认特定格式）
- 浏览器兼容问题（建议用 Chromium/Firefox）

**恢复步骤**：
1. 确认固件 ≤ 31MB（留空间给 uboot/factory/eeprom）
2. 确认固件是 OpenWrt sysupgrade 或 breed-compatible 格式
3. 尝试换个浏览器

**recoverable**：true
**相关脚本**：breed_flash

## [partition_full] Flash 空间不足

**现象**：刷写时报空间不足

**原因**：
- firmware 分区只有 ~31.7MB，固件太大
- 旧固件 overlay 占用空间

**恢复步骤**：
1. 使用 squashfs-only 固件（不含 extra 软件包）
2. `sysupgrade -n` （不保留配置，可回收 overlay 空间）
3. 如果是 OpenWrt，用 `mtd erase firmware` 清空后重刷

**recoverable**：true
**相关脚本**：ssh_sysupgrade
