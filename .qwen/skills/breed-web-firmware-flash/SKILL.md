---
name: breed-web-firmware-flash
description: 通过 breed Web 接口刷写固件的完整 5 步协议流程——POST upload 加载、GET upgrading 触发、POST 轮询、动态 magic reboot；只能刷 initramfs/裸 kernel/编程器固件，sysupgrade 必须从 initramfs shell 内 sysupgrade（已实测 Newifi D2 1.1 r1237）
source: auto-skill
extracted_at: '2026-06-10T19:55:00.000Z'
---

# Breed Web 接口刷写固件 —— 完整 5 步协议

## 适用场景

路由器已经进入 **breed Web 恢复模式**（在 `http://192.168.1.1/`），需要把 sysupgrade 固件从 PC 刷到路由器，**全程走 HTTP**（不靠 SSH / TFTP / 串口）。

**典型链路**：`breed_enter.py` 进入 breed → 本 skill 上传 + 触发 + 轮询 + 重启 → 路由器启动到新固件。

## 真实协议（2026-06-10 实测 Newifi D2 / Breed 1.1 r1237）

⚠️ **不要靠看 JS 源码推断协议**——`/upgrading.html` 的 JS 看起来在轮询，但实际 POST + GET 哪个才触发刷写必须抓真实流量确认。本 skill 的所有步骤都经过用户抓包验证。

### 5 步流程

```
1. POST /upload.html          文件加载到 breed 内存
2. GET  /upgrading.html       触发实际刷写（不是 POST!）
3. POST /upgrade_query.html   轮询进度（每秒一次，返纯数字 %）
4. GET  /reboot.html          提取动态 magic 值
5. POST /rebooting.html       用动态 magic 触发重启
```

### Step 1: POST /upload.html

```bash
curl -X POST http://192.168.1.1/upload.html \
  -F "boot_file=" \
  -F "fw_check=1" \
  -F "fw_file=@<固件>" \
  -F "flash_layout=reference" \
  -F "fw_type=generic" \
  -F "submit=Upload"
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `fw_type` | ✅ | `generic`（常规）/ `fullflash`（编程器） |
| `fw_file` + `fw_check=1` | ✅ | 固件本体 |
| `flash_layout` | ✅ | Newifi D2 选 `reference`（kernel @ 0x50000） |
| `submit` | ✅ | 固定 `Upload` |
| `boot_file` + `boot_check=1` | ❌ | 同步刷 bootloader 时用 |
| `eeprom_file` + `eeprom_check=1` | ❌ | 同步刷 Wi-Fi 校准时用 |

⚠️ `boot_file=` 要**显式发空字段**——浏览器即使不上传 bootloader 也会发这个空 `name`，不发的话 breed 的表单校验可能不通过。

**响应**：HTML 确认页（~4257 字节），含：
- `has_fw = "1"` ← 文件加载成功
- `has_boot = "0"` / `has_eeprom = "0"` / `has_fullflash = "0"`
- 表格里显示：文件名 / 大小 / MD5

**不要从响应里拿文件大小/校验**——直接在本地校验完再上传。

### Step 2: GET /upgrading.html（关键陷阱）

```bash
curl http://192.168.1.1/upgrading.html
```

**这个 GET 才是"开始刷写"的触发点**——不是 POST upload，也不是 POST 任何东西。

- 响应：2802 字节 HTML（含 `ajax.js` 引用）
- HTML 文本说"您选择的操作正在进行"——意味着刷写已经在跑了
- 之后 ajax.js 会自动 POST 轮询 `/upgrade_query.html`

⚠️ 跳过这一步会怎样：POST `/upload.html` 只是把文件加载到 RAM，**不会真正写入 flash**。`/upgrade_query.html` 会一直返 `0` 不动。

### Step 3: POST /upgrade_query.html

```bash
curl -X POST http://192.168.1.1/upgrade_query.html
```

`ajax.js` 源码（实测）：
```javascript
xmlhttp.open("post", url, false);
xmlhttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
xmlhttp.send("");
```

- **方法必须是 POST**——GET 也能拿到数字但**不触发 100% 后的 reboot 状态机**
- 请求体是空字符串 `""`
- Content-Type: `application/x-www-form-urlencoded`
- 响应：纯数字（字符串），如 `5` / `47` / `100`

**轮询频率**：1s 一次（看 `ajax.js` 的 `setInterval(..., 1000)`）。

**进度行为**：
- 前 30~40s 一直 `0`（breed 在准备）
- 然后 `1, 3, 4, 5, 7, 8...` 慢慢涨
- 总耗时约 80~120s 从 0 → 100
- 数字到 `100` 时返回完成

⚠️ 数字 `100` 本身**不会**触发路由器的实际 reboot——`ajax.js` 只是把文字改成"更新完成"然后 JS 跳转到 `/`。要真正重启还得走 Step 4-5。

### Step 4: GET /reboot.html（提取动态 magic）

```bash
curl http://192.168.1.1/reboot.html | grep -oE 'name="magic" value="[0-9]+"'
```

⚠️ **HTML 里的 magic 值是误导性的**——静态 HTML 写 `value="139482"` 但实际是 server 动态生成。

实测过的 magic 值：
- HTML 静态读出来：`139482`
- Firefox 抓包：`73994`
- 每次 `GET /reboot.html` 都不一样

正确做法：**每次 reboot 前 GET 一次提取当前值**。

### Step 5: POST /rebooting.html

```bash
magic=$(curl -s http://192.168.1.1/reboot.html | grep -oE 'name="magic" value="[0-9]+"' | grep -oE '[0-9]+')
curl -X POST http://192.168.1.1/rebooting.html \
  -F "submit=Reboot" \
  -F "magic=$magic"
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `submit` | ✅ | 固定 `Reboot` |
| `magic` | ✅ | **从 GET /reboot.html 提取的当前值**（不是 HTML 静态值） |

**响应**：HTTP 302 → `/`

⚠️ 用了过期/错误的 magic：返 302 但路由器不重启，breed 一直停留。

## 完整 Python 实现骨架

```python
import requests
import re
import time

ROUTER = "http://192.168.1.1"
FIRMWARE = "immortalwrt-ramips-mt7621-d-team_newifi-d2-squashfs-sysupgrade.bin"


def breed_flash(firmware_path: str, timeout: int = 180) -> dict:
    """完整 5 步刷写流程. 返回 {"ok": bool, ...}"""

    # Step 1: 上传固件到 breed 内存
    with open(firmware_path, "rb") as f:
        r = requests.post(
            f"{ROUTER}/upload.html",
            files={
                "boot_file": ("", b""),  # 浏览器必发的空字段
                "fw_file": (firmware_path, f, "application/octet-stream"),
            },
            data={
                "fw_type": "generic",
                "fw_check": "1",
                "flash_layout": "reference",
                "submit": "Upload",
            },
            timeout=60,
        )
    r.raise_for_status()
    if 'has_fw = "1"' not in r.text:
        return {"ok": False, "error": "upload rejected", "raw": r.text[:500]}

    # Step 2: GET /upgrading.html —— 触发实际刷写!
    requests.get(f"{ROUTER}/upgrading.html", timeout=5)

    # Step 3: POST 轮询进度
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.post(
            f"{ROUTER}/upgrade_query.html",
            data="",  # ajax.js 发的就是空 body
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        progress = r.text.strip()
        if progress == "100":
            break
        time.sleep(1)
    else:
        return {"ok": False, "error": f"flash timeout after {timeout}s"}

    # Step 4: GET /reboot.html 提取动态 magic
    r = requests.get(f"{ROUTER}/reboot.html", timeout=5)
    m = re.search(r'name="magic" value="(\d+)"', r.text)
    if not m:
        return {"ok": False, "error": "magic not found in /reboot.html"}
    magic = m.group(1)

    # Step 5: POST /rebooting.html 触发 reboot
    requests.post(
        f"{ROUTER}/rebooting.html",
        data={"submit": "Reboot", "magic": magic},
        timeout=10,
    )

    return {"ok": True, "magic_used": magic, "flashed": firmware_path}
```

## 成功信号检测

刷写完成后等 30~90s 看重启：

```bash
# 检测 ImmortalWrt / OpenWrt 已上线
curl -sI http://192.168.1.1/ | grep -i "^Server:\|^Connection:"
# 期望: 没有 "Server: Breed/1.0", 而是有 "Connection: Keep-Alive" (uhttpd)

curl -sI http://192.168.1.1/cgi-bin/luci
# 期望: HTTP 403 + "x-luci-login-required: yes"
```

| 信号 | 含义 |
|------|------|
| `Server: Breed/1.0` | 还在 breed（刷写失败或没触发） |
| `Connection: Keep-Alive` (无 Server 字段) | uhttpd（ImmortalWrt/OpenWrt 默认 Web 服务） |
| `HTTP 403 + x-luci-login-required` | LuCI 跑起来了，但未登录 |

## 不能直接刷的文件类型（**关键** —— 2026-06-10 用户纠正）

⚠️ **breed 严禁刷入 sysupgrade 固件！** Sysupgrade 是 OpenWrt 专有格式（含 metadata 头/签名/分区表），breed 不识别。**`has_fw=1` 可能是假象**——breed 把数据写到 RAM 后 UI 看着像在处理，但写到 flash 的字节不会被 bootloader 正确解析。

| 文件 | 能不能直接刷 | 原因 |
|------|------------|------|
| `*-squashfs-sysupgrade.bin` | ❌ **不能** | OpenWrt 专有格式（含 metadata 头/签名/分区表），breed 不识别 |
| `*-initramfs-kernel.bin` | ✅ | **裸 kernel+initrd 镜像**，breed 直接写到 firmware 分区作为新 kernel 引导 |
| `*-factory.bin` | ⚠️ | 部分场景 breed 拒绝（"非小米 .bin 报 code:1554"） |
| `fullflash_*.bin` | ✅ | 编程器固件，走 `fw_type=fullflash` 路径 |

### 完整刷 OpenWrt/ImmortalWrt 的两段式流程

**第一段（在 breed 里）**：
1. 上传 `*-initramfs-kernel.bin`（**不是 sysupgrade**）
2. 走完整 5 步触发刷写 + 重启
3. 路由器启动到 **initramfs 系统**（完整 Linux shell + 网络，但无持久 rootfs）

**第二段（在 initramfs shell 里）**：
```bash
# 1. 设置网络（initramfs 通常已配 DHCP）
ip addr show

# 2. scp 上传 sysupgrade
scp /path/to/immortalwrt-25.12.0-ramips-mt7621-d-team_newifi-d2-squashfs-sysupgrade.bin root@192.168.1.1:/tmp/

# 3. 写持久 rootfs
sysupgrade -n /tmp/immortalwrt-...-squashfs-sysupgrade.bin
# -n = 不保留配置（清空 NVRAM 等同于首次刷机）
```

执行 `sysupgrade` 后路由器会**自动重启**到新固件，此时才是真正"持久安装"。

### 为什么 breed 不能直接刷 sysupgrade

| 维度 | initramfs-kernel | squashfs-sysupgrade |
|------|-----------------|---------------------|
| 文件结构 | 裸 uImage/uImage.itb | OpenWrt 专有容器（header + 签名 + kernel + rootfs + metadata） |
| 头部 magic | TRX/uImage | OpenWrt 特定格式（`7z` + `hsqs` + json 头） |
| 适用烧录工具 | breed / U-Boot 通用 | `sysupgrade` 专用（解压、重分区、校验） |
| 写到 flash 后的行为 | 直接作为 kernel 启动 | **不可预测**（被 breed 当成 raw binary 写，要么乱码要么长度错位） |

breed 的 5 步刷写协议对两种文件**一视同仁**——都用 `POST /upload.html` 接收、用 `flash_layout=reference` 写偏移、用 `GET /upgrading.html` 触发。但**只有 initramfs 镜像能被 bootloader 正确解析**。sysupgrade 写进去后路由器启动时会因为 magic 错而回 breed 或 panic。

## 错误 reason 分类

| reason | 触发条件 | recoverable |
|--------|---------|-------------|
| `upload_rejected` | `has_fw=0` 出现在响应里 | true（换固件或换字段） |
| `flash_timeout` | 进度 < 100 超过 timeout | true（重试） |
| `magic_not_found` | `/reboot.html` HTML 没有 magic 字段 | true（重 GET） |
| `sysupgrade_not_supported_in_breed` | 上传了 `*-squashfs-sysupgrade.bin`（用户错选） | true（改用 initramfs 走两段流程） |
| `initramfs_no_persistence` | 刷入 initramfs 后用户期望持久化 | true（从 initramfs shell 内 sysupgrade 一次） |
| `network_unreachable` | 路由器不通 | true（重试 breed_enter） |

## 与现有技能的搭配

- **`breed-udp-abort-enter`** —— 上游：本 skill 假设已经在 breed 模式（用 breed_enter.py 进入）
- **`udp-multi-nic-bind`** —— 上游：breed_enter.py 的 `--iface` / `--bind-ip` 在多网卡机器上必需
- **`step-script-default-silent-debug`** —— 本脚本遵循同样的 `--debug` 模式
- **`unix-philosophy-router-refactor`** —— 步骤脚本骨架（argparse / JSON 输出 / 单文件）参考此 skill

## 验收清单

写完一个 breed_web_flash 风格的脚本后：

- [ ] POST `/upload.html` 用 multipart，含 `boot_file=` 空字段
- [ ] **GET**（不是 POST）`/upgrading.html` 触发刷写
- [ ] **POST**（不是 GET）`/upgrade_query.html` 轮询
- [ ] 轮询 body 是空字符串，Content-Type 是 `application/x-www-form-urlencoded`
- [ ] 重启前 **GET /reboot.html 重新提取 magic**
- [ ] POST `/rebooting.html` 用刚提取的 magic，不是 HTML 静态值
- [ ] 成功信号检测：Server header / LuCI 头
- [ ] `--timeout` 默认值（180s）足够覆盖 80s 刷写 + 90s 重启
- [ ] `troubleshooting.md` 包含 `[stale_magic]` `[sysupgrade_not_supported_in_breed]` `[query_should_be_post]` 条目
- [ ] JSON 失败时带 `reason` + `recoverable` 字段
- [ ] 不在 JSON 里放 `next_steps` / `recovery`——这些走 `flash-pipeline.md`

## 复用到其他 Web bootloader

如果未来有其他 bootloader 实现类似 HTTP API（`/upload` + `/trigger` + `/query` + `/reboot`），按本模式重写：

1. 替换 endpoint + payload
2. 重点：找出**触发动作的真正 HTTP method**（抓包确认，不要看 JS 推断）
3. 重点：**所有 hidden 字段都按动态值处理**，先 GET 再 POST
4. 改 `reason` 字符串
5. 更新 `troubleshooting.md` 对应条目
