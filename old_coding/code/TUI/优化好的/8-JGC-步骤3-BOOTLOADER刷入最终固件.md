# JGC 步骤 3：BOOTLOADER 刷入最终固件

## 界面展示（等待中）
```
-----JGC Q10/Q20 批量刷机模式-----
步骤3：BOOTLOADER刷入预期固件
等待IP 192.168.1.1 上线 （BOOTLOADER有点毛病，ping到就算上线）




-----Powered by Haku Studio 2026-----
```

## 刷入中
```
-----JGC Q10/Q20 批量刷机模式-----
步骤3：BOOTLOADER刷入预期固件
192.168.1.1 上线
正在刷入预期固件



-----Powered by Haku Studio 2026-----
```

## 刷入成功
```
-----JGC Q10/Q20 批量刷机模式-----
步骤3：BOOTLOADER刷入预期固件
192.168.1.1 上线
正在刷入预期固件
刷入成功！
正在等待产品上线
检测到 10.11.12.1 上线，mac地址未被记录，库存量+1


-----Powered by Haku Studio 2026-----
```

## 逻辑说明

### 步骤 3 流程
1. **等待 Uboot 上线**：持续 ping 192.168.1.1
   - **注意**：uboot 的 ping 响应可能不正常，"ping 到就算上线"
   - 建议增加 HTTP 探测：尝试访问 `http://192.168.1.1/` 或 `/status.html`
2. **HTTP 可用验证**：ping 通后尝试 HTTP 访问
   - uboot httpd 可能返回非标准响应，需要处理异常
3. **执行刷机**：调用 `uboot_flash.py`
   - POST 固件到 `/upload.cgi`
   - 轮询 `/status.html` 检查进度
   - 完成后 GET `/reboot.cgi` 重启
4. **等待最终系统上线**：持续 ping 10.11.12.1
5. **库存统计**：
   - 获取 10.11.12.1 的 MAC 地址
   - 检查 `mac_inventory.json` 是否已记录
   - 新设备：计数 +1，写入记录
   - 已刷设备：显示已刷过，计数不变
6. **返回主菜单**：等待 2 秒后返回 JGC 主菜单

### Uboot 检测优化
由于 uboot 的 ping 行为不稳定，建议：
```python
# 伪代码
def is_uboot_online(ip):
    # 1. 先尝试 ping
    if ping(ip, count=1, timeout=1) == 0:
        # 2. 再尝试 HTTP 访问
        try:
            response = requests.get(f"http://{ip}/", timeout=3)
            # uboot httpd 返回可能不标准，不抛异常就算在线
            return True
        except:
            # HTTP 失败但 ping 成功，可能 uboot 已启动但 httpd 未就绪
            # 可以尝试多次
            pass
    return False
```

### 失败处理
**可能原因**：
- uboot 未正常启动（刷 bootloader 失败）
- HTTP 访问超时（uboot httpd 启动慢）
- 固件文件损坏或不匹配

**处理**：
- 显示错误信息
- 提示检查固件文件路径：`./image/sharewifi_jqg_q20_1.1.bin`
- 可选择重试或返回主菜单

## 小提示
1. Uboot httpd 是轻量级 HTTP 服务，响应可能不标准，需要处理 `BadStatusLine` 异常
2. 刷机进度通过 `/status.html` 获取，返回 JSON 格式：`{"status":"done","progress":"100"}`
3. 最终系统 IP 为 10.11.12.1，与 CR660X 相同
4. 固件文件路径：`./image/sharewifi_jqg_q20_1.1.bin`
5. 刷机时间约 3-5 分钟，取决于路由器硬件
6. 此阶段不需要 HTTP 服务器（chfs）
7. 库存记录文件与 CR660X 共享：`mac_inventory.json`
