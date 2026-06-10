# JGC 步骤 2：PDCN 刷入 BOOTLOADER

## 界面展示（等待中）
```
-----JGC Q10/Q20 批量刷机模式-----
步骤2：PDCN刷入BOOTLOADER
等待IP 192.168.123.1 上线




-----Powered by Haku Studio 2026-----
```

## 成功执行
```
-----JGC Q10/Q20 批量刷机模式-----
步骤2：PDCN刷入BOOTLOADER
192.168.123.1 上线！（这里要的是能够http过登录，ping到之后反复尝试http登录）
自动认证 admin/admin
执行SSH命令，下载服务端
系统已重启
进入下一阶段


-----Powered by Haku Studio 2026-----
```

## 逻辑说明

### 步骤 2 流程
1. **等待 PDCN 系统上线**：持续 ping 192.168.123.1
2. **HTTP 登录验证**：ping 通后，尝试 HTTP 登录验证
   - 访问 `http://192.168.123.1/cgi-bin/luci`
   - 使用 Basic 认证：admin/admin
   - 如果返回 401 或登录失败，持续重试（最多 10 次）
3. **HTTP 可用**：确认 PDCN 系统可访问后执行刷机
   - `pdcn_put_bootloader.py`：通过 wget 从主机下载 bootloader
     - 下载 URL：`http://192.168.123.2:8080/chfs/shared/pb-boot.img`
   - `pdcn_flash_bootloader.py`：刷入 bootloader 到 Bootloader 分区
   - `pdcn_reboot.py`：重启进入 uboot
4. **自动进入下一阶段**：等待重启后进入步骤 3（uboot 刷最终固件）

### HTTP 服务器依赖
**必须条件**：
- `chfs-linux-amd64-3.1` 必须在主机上运行
- 监听地址：192.168.123.2:8080
- 共享目录：`./chfs/shared/`
- 文件：`pb-boot.img`

**启动检查**：
- 在步骤 1 完成后自动启动（JGC 主菜单已有自动启动逻辑）
- 状态显示：RUNNING / STOPPED

**启动命令**：
```bash
cd /home/xmb505/alpine-router-flash/JGC-Qx  # 或 JGC-Q10
nohup ./chfs-linux-amd64-3.1 &
```

### 失败处理
**可能原因**：
- HTTP 服务器未运行或路径错误
- 网络连接问题（路由器无法访问主机）
- 基本认证失败（PDCN 系统可能被重置为默认密码）

**处理**：
- 显示错误信息
- 提示检查 HTTP 服务器状态
- 可选择重试或返回主菜单

## 小提示
1. PDCN 系统使用 Basic 认证（admin:admin），无需复杂加密
2. wget 下载速度取决于网络，通常 10-30 秒
3. bootloader 文件大小约 2-3 MB
4. 刷入 bootloader 后，路由器重启进入 uboot 模式，IP 变为 192.168.1.1
5. 此阶段 HTTP 服务器必须运行，否则无法下载 bootloader
6. 如果 HTTP 服务器已在运行，不会重复启动
