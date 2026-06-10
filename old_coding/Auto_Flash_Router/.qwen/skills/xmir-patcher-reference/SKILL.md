---
name: xmir-patcher-reference
description: 小米路由器刷机工具集 xmir-patcher，包含多种机型的登录加密、SSH 注入等实现
type: reference
---

小米路由器自动脚本参考仓库：[openwrt-xiaomi/xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher)

关键文件：
- `gateway.py`: `web_login()` 方法实现了完整的新旧加密登录逻辑；`xqhash()` 根据 `encryptmode` 自动选择 SHA1/SHA256
- `xqmodel.py`: 设备型号映射表（如 RD03=model 75）
- connect*.py: 不同机型的连接/刷机脚本

**如何应用：** 当需要适配新机型时，先查看 xqmodel.py 确认型号是否已支持，然后参考 gateway.py 中的 `web_login()` 和 `detect_device()` 逻辑。
