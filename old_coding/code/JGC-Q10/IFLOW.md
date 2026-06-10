# JGC-Qx 路由器批量刷机工具

## 项目概述

这是一个用于JCG路由器批量刷机的Python工具集。项目包含十三个主要脚本，用于自动化获取路由器默认密码、登录路由器获取认证信息、配置路由器WAN口模式和WiFi配置，执行固件升级操作，以及在刷入PDCN系统后上传和刷入bootloader，为后续的批量刷机操作做准备。项目还包括专门针对uboot环境的刷机脚本，支持非标准HTTP响应的处理，以及两个整合脚本用于自动化执行完整的刷机流程。

## 脚本说明

### 1. get_passwd.py

此脚本用于从路由器的登录页面自动获取默认密码。

#### 功能
- 访问路由器登录页面 (默认IP: 192.168.2.1)
- 解析页面源代码以查找默认密码
- 支持通过命令行参数指定路由器IP地址

#### 使用方法
```bash
# 使用默认IP地址
python3 get_passwd.py

# 指定路由器IP地址
python3 get_passwd.py 192.168.1.1
```

#### 返回值
- 如果成功找到密码，输出密码字符串
- 如果未找到密码，输出null

### 2. get_stok.py

此脚本用于使用密码登录路由器并获取stok令牌和sysauth认证信息，这些信息用于后续的API调用。

#### 功能
- 使用Base64编码用户名和密码
- 向路由器发送登录请求
- 解析响应头以提取stok令牌和sysauth认证信息

#### 使用方法
```bash
# 使用指定密码登录并获取stok和sysauth
python3 get_stok.py your_password
```

#### 返回值
- 如果成功获取stok和sysauth，分别输出：
  - stok=令牌值
  - sysauth=认证值
- 如果登录失败，输出：
  - stok=null
  - sysauth=null

### 3. set_wan_mode.py

此脚本用于设置路由器WAN口为DHCP模式。

#### 功能
- 使用stok和sysauth认证信息
- 向路由器发送配置请求，将WAN口设置为DHCP模式

#### 使用方法
```bash
# 使用stok和sysauth设置WAN口为DHCP模式
python3 set_wan_mode.py stok_value sysauth_value
```

#### 返回值
- 如果成功设置，输出OK
- 如果设置失败，输出null

### 4. set_wifi_mode.py

此脚本用于设置路由器WiFi配置。

#### 功能
- 使用passwd、stok和sysauth认证信息
- 向路由器发送配置请求，设置WiFi名称、密码等参数

#### 使用方法
```bash
# 使用passwd、stok和sysauth设置WiFi配置
python3 set_wifi_mode.py passwd stok sysauth
```

#### 返回值
- 如果成功设置，输出OK
- 如果设置失败，输出null

### 5. put_firmware.py

此脚本用于上传固件到路由器并验证固件。

#### 功能
- 读取固件文件 (./image/JCG-Q20-PDCN.bin)
- 上传固件到路由器
- 验证固件是否正确上传

#### 使用方法
```bash
# 使用stok和sysauth上传并验证固件
python3 put_firmware.py stok_value sysauth_value
```

#### 返回值
- 如果成功上传并验证固件，输出OK
- 如果上传或验证失败，输出null

### 6. confirm_upgrade.py

此脚本用于确认路由器固件升级。

#### 功能
- 使用stok和sysauth认证信息
- 向路由器发送确认升级请求

#### 使用方法
```bash
# 使用stok和sysauth确认固件升级
python3 confirm_upgrade.py stok_value sysauth_value
```

#### 返回值
- 如果成功确认升级，输出OK
- 如果确认升级失败，输出null

### 7. cancel_upgrade.py

此脚本用于取消路由器固件升级。

#### 功能
- 使用stok和sysauth认证信息
- 向路由器发送取消升级请求

#### 使用方法
```bash
# 使用stok和sysauth取消固机升级
python3 cancel_upgrade.py stok_value sysauth_value
```

#### 返回值
- 如果成功取消升级，输出OK
- 如果取消升级失败，输出null

### 8. pdcn_put_bootloader.py

此脚本用于在老毛子PDCN系统上上传bootloader。

#### 功能
- 使用Basic认证登录路由器 (admin:admin)
- 执行wget命令从服务器下载bootloader到路由器
- 支持通过命令行参数指定路由器IP地址

#### 使用方法
```bash
# 使用默认IP地址
python3 pdcn_put_bootloader.py

# 指定路由器IP地址
python3 pdcn_put_bootloader.py 192.168.123.1
```

#### 返回值
- 如果成功上传bootloader，输出命令执行结果
- 如果上传失败，输出null

### 9. pdcn_flash_bootloader.py

此脚本用于在老毛子PDCN系统上刷入bootloader。

#### 功能
- 使用Basic认证登录路由器 (admin:admin)
- 执行mtd_write命令将bootloader刷入Bootloader分区
- 支持通过命令行参数指定路由器IP地址

#### 使用方法
```bash
# 使用默认IP地址
python3 pdcn_flash_bootloader.py

# 指定路由器IP地址
python3 pdcn_flash_bootloader.py 192.168.123.1
```

#### 返回值
- 如果成功刷入bootloader，输出命令执行结果
- 如果刷入失败，输出null

### 10. pdcn_reboot.py

此脚本用于重启老毛子PDCN系统路由器。

#### 功能
- 使用Basic认证登录路由器 (admin:admin)
- 执行reboot命令重启路由器
- 支持通过命令行参数指定路由器IP地址

#### 使用方法
```bash
# 使用默认IP地址
python3 pdcn_reboot.py

# 指定路由器IP地址
python3 pdcn_reboot.py 192.168.123.1
```

#### 返回值
- 如果成功执行重启命令，输出命令执行结果
- 如果执行失败，输出null

### 11. uboot_flash.py

此脚本用于在uboot环境下批量刷写路由器固件，特别针对uboot的httpd非标准响应进行了优化。

### 12. official_flash_all.py

此脚本用于自动化执行完整的官方固件刷机流程，整合了所有单独的刷机步骤。

#### 功能
- 自动检测路由器是否在线 (默认IP: 192.168.2.1)
- 自动获取路由器默认密码或手动输入
- 自动登录路由器获取stok和sysauth认证信息
- 上传固件并验证
- 确认固件升级
- 等待路由器重启完成
- 单次执行，完成后自动退出

#### 使用方法
```bash
# 直接运行脚本
python3 official_flash_all.py
```

#### 刷机流程
1. 检测路由器是否在线 (ping 192.168.2.1)
2. 自动获取默认密码或要求手动输入
3. 登录路由器获取stok和sysauth
4. 上传固件 (./image/JCG-Q20-PDCN.bin)
5. 确认固件升级
6. 等待路由器重启并重新上线
7. 刷机完成，脚本自动退出

#### 特殊处理
- 自动处理密码获取失败的情况，提示用户手动输入
- 正确解析各子脚本的输出结果
- 等待路由器重启并检测是否重新上线
- 提供详细的进度提示和错误信息

### 13. pdcn_flash_all.py

此脚本用于自动化执行完整的PDCN系统bootloader刷入流程，整合了所有PDCN相关的刷机步骤。

#### 功能
- 自动检测路由器是否在线 (默认IP: 192.168.123.1)
- 自动上传bootloader到路由器
- 自动刷入bootloader到Bootloader分区
- 自动重启路由器
- 循环执行，适合批量刷机操作

#### 使用方法
```bash
# 直接运行脚本
python3 pdcn_flash_all.py
```

#### 刷机流程
1. 检测路由器是否在线 (ping 192.168.123.1)
2. 上传bootloader到路由器 (/tmp/pb-boot.img)
3. 刷入bootloader到Bootloader分区
4. 重启路由器
5. 等待10秒后开始下一轮刷机流程

#### 特殊处理
- 循环执行，适合批量刷机操作
- 自动处理路由器不在线的情况，提示用户检查连接
- 提供详细的进度提示和错误信息
- 每轮刷机完成后自动等待10秒再开始下一轮

#### 功能
- 使用ping检测路由器是否在线
- 向uboot的upload.cgi上传固件文件
- 解析非标准HTTP响应，正确处理BadStatusLine异常
- 监控刷机进度，检测status.html返回的状态
- 自动重启路由器并循环执行刷机流程

#### 使用方法
```bash
# 直接运行脚本
python3 uboot_flash.py
```

#### 刷机流程
1. 使用ping检测192.168.1.1是否在线
2. 向http://192.168.1.1/upload.cgi上传固件文件
3. 解析返回的HTML，识别"successfully uploaded"关键字
4. 定期访问http://192.168.1.1/status.html获取刷机进度
5. 等待status为"done"且progress为"100"
6. 访问http://192.168.1.1/reboot.cgi重启路由器
7. 等待5秒后开始下一个刷机循环

#### 特殊处理
- 使用ping命令检测路由器在线状态，而非HTTP请求
- 正确处理uboot httpd的非标准HTTP响应（BadStatusLine）
- 从异常信息中提取状态和进度信息
- 支持循环执行，适合批量刷机操作

#### 固件文件
- 固件路径: ./image/sharewifi_jqg_q20_1.1.bin
- 默认IP地址: 192.168.1.1

## 技术细节

### 路由器登录机制
1. 路由器默认IP地址: 192.168.2.1
2. 登录端点: http://192.168.2.1/cgi-bin/luci
3. 登录数据:
   - username: root (Base64编码)
   - password: 路由器默认密码 (Base64编码)
   - pc_mac: 00:0E:C6:34:2F:5A

### WAN口设置机制
1. API端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGnetwork/firstSetup_wan
2. 需要提供stok和sysauth认证信息
3. 需要设置特定的HTTP头部信息和Cookie

### WiFi设置机制
1. API端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGnetwork/firstSetup_wifi
2. 需要提供passwd、stok和sysauth认证信息
3. 需要设置特定的HTTP头部信息和Cookie
4. WiFi配置包括：
   - 2.4G WiFi名称: ChinaNet-e4Kn
   - 5G WiFi名称: ChinaNet-e4Kn-5G
   - 2.4G WiFi密码: xZfxUvg5
   - 管理密码保持不变（与输入的passwd相同）

### 固件升级机制
1. 固件文件路径: ./image/JCG-Q20-PDCN.bin
2. 固件上传端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/upload_firmware
3. 固件验证端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/check_firmware
4. 确认升级端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/upgrade?keep_config=false
5. 取消升级端点: http://192.168.2.1/cgi-bin/luci/;stok={stok}/api/JCGFirmware/download_firmware_cancel

### PDCN系统操作机制
1. 路由器默认IP地址: 192.168.123.1
2. 命令执行端点: http://192.168.123.1/apply.cgi
3. 命令结果获取端点: http://192.168.123.1/console_response.asp
4. 认证方式: Basic认证 (Authorization: Basic YWRtaW46YWRtaW4=)
5. bootloader文件路径: /tmp/pb-boot.img
6. bootloader刷写命令: mtd_write write /tmp/pb-boot.img Bootloader
7. bootloader下载命令: wget -O /tmp/pb-boot.img http://192.168.123.2:8080/chfs/shared/pb-boot.img

### Uboot刷机机制
1. 路由器默认IP地址: 192.168.1.1
2. 固件上传端点: http://192.168.1.1/upload.cgi
3. 状态检查端点: http://192.168.1.1/status.html
4. 重启端点: http://192.168.1.1/reboot.cgi
5. 固件文件路径: ./image/sharewifi_jqg_q20_1.1.bin
6. 检测方式: 使用ping命令检测路由器在线状态
7. 响应处理: 正确处理非标准HTTP响应，从异常信息中提取状态

### 安全注意事项
1. 脚本禁用了SSL证书验证警告，因为在本地网络环境中使用
2. 所有通信均为HTTP明文传输，不适用于生产环境
3. uboot刷机脚本特别处理了非标准HTTP响应，避免误判为错误

## 开发环境
- Python 3.x
- 依赖库: requests
- 系统工具: ping, wget, mtd_write

## 固件文件
- JCG-Q20-PDCN.bin - 主要固件文件
- sharewifi_jqg_q20_1.1.bin - uboot刷机专用固件
- pb-boot.img - bootloader镜像文件
- pb-boot.s19 - bootloader S19格式文件

## 使用流程
### 标准刷机流程：
1. 使用get_passwd.py获取路由器默认密码
2. 使用get_stok.py和获取的密码登录路由器获取stok和sysauth
3. 使用set_wan_mode.py设置路由器WAN口模式
4. 使用set_wifi_mode.py设置路由器WiFi配置
5. 使用put_firmware.py上传并验证固件
6. 使用confirm_upgrade.py确认固件升级或使用cancel_upgrade.py取消升级
7. 等待路由器完成升级过程并进入PDCN系统
8. 使用pdcn_put_bootloader.py上传bootloader到路由器
9. 使用pdcn_flash_bootloader.py将bootloader刷入Bootloader分区
10. 使用pdcn_reboot.py重启路由器完成刷机过程

### 自动化刷机流程（推荐）：
1. 运行official_flash_all.py自动执行官方固件刷机流程
2. 脚本会自动完成密码获取、认证、固件上传和升级确认
3. 等待路由器重启完成后，脚本自动退出

### PDCN系统bootloader刷入流程：
1. 运行pdcn_flash_all.py自动执行PDCN系统bootloader刷入流程
2. 脚本会自动完成bootloader上传、刷入和重启操作
3. 脚本循环执行，适合批量刷机操作

### Uboot批量刷机流程：
1. 确保路由器进入uboot模式并启动HTTP服务
2. 运行uboot_flash.py脚本
3. 脚本会自动循环执行检测、上传、监控、重启流程
4. 每个循环间隔5秒，适合批量刷机操作