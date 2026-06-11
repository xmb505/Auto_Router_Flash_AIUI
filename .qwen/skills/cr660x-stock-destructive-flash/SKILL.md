---
name: cr660x-stock-destructive-flash
description: CR660X (CR6606 联通 / CR6608 移动 / CR6609 越南) stock 固件迁移 + 破坏性刷机完整流程：JS 反推 AES-CBC newPwd → smartcontroller scene 启用 SSH → 真 SSH 验证 → scp 上传。强调"不抄 flasher.py 错误实现"、"不走辅助 WiFi 注入"、"不做双系统"
source: auto-skill
extracted_at: '2026-06-11T11:37:31.075Z'
---

# CR660X stock 固件迁移 + 破坏性刷机

## 适用场景

把 `old_coding/code/src/cr660x/flasher.py`（含错误实现）剥壳成 `src/project/cr660x/` 下完整流水线。**核心精神**：

- CR660X 是小米体系但**不是** PBoot/breed，HTTP 服务是 stock 自带 nginx/1.12.2
- **绝对不要** 抄 flasher.py 的 `extendwifi_connect` 辅助 WiFi 注入路径（已废，硬编码 SSID/密码）
- **绝对不要** 抄 flasher.py 的 SHA1 哈希算 newPwd（错的！JS 里实际是 AES-CBC）
- 走破坏性刷机路线，**不**做双系统切换

前置（已知 skill）：
- `step-script-migrate-from-old` — 5 步迁移流程骨架
- `step-script-default-silent-debug` — `--debug` + 模块全局门控
- `unix-philosophy-router-refactor` — 项目哲学
- `xiaomi-js-crypto-反向-engineer` — JS 密码学反推

## CR660X 独特性（3 个关键设计点）

### 1. flasher.py 里的 newPwd 是错的

```python
# flasher.py 错误实现
password_hash = self._calc_password(new_password, key, nonce)  # SHA1 hash
# ...
"newPwd={password_hash}&oldPwd={password_hash}"
```

实际 JS 里的 newPwd：
```js
// init.<hash>.js 反推
oldPwd = SHA1(nonce + SHA1(old_pwd + key))                       // 明文 old_pwd
newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7).toString()
routerPwd = 明文 new_pwd
```

**症状**：照搬 flasher.py 跑完 init 后，密码既不是 admin 也不是 newpass123（变未知值）。

**修正**：照搬 ax6/ax3600 的 `calc_new_pwd`（AES-CBC）：
```python
def calc_new_pwd(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    aes_key = bytes.fromhex(sha1_hex(old_pwd + key)[:32])
    plain = sha1_hex(new_pwd + key).encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()
```

### 2. nginx/1.12.2 = stock 固件，**不是** PBoot

```
Server: nginx/1.12.2
```

容易让人误判是 PBoot（PandoraBox bootloader），但用户明确说"我还没刷pb-boot"。**这是 stock 固件自带的 HTTP server**，提供 `init.html` + `init.<hash>.js` + `/cgi-bin/luci/api/xqsystem/*` 完整小米体系 API。

判定：
- 看到 nginx/1.12.2 + 完整 xqsystem 端点 → **stock CR660X**，不是 PBoot
- 看到 `Server: Breed/1.0` → 那是 breed（CR660X 还未刷这个）

### 3. 走 smartcontroller 注入（跟 ax6 同路径）

flasher.py 走 `extendwifi_connect` 辅助 WiFi 注入，**xmir 日志明确标 WARN: not working**。改走 ax6 一样的 smartcontroller scene 路径（`request_smartcontroller` + `wan_block` + mac 字段注入）：

- 共用 `ax6-smartcontroller-exploit` skill 的所有细节（hackCheck 探测、time -s 2033 验证、504/-101 预期超时、dropbear release 锁 sed、echo 分块写 /tmp/e）
- 唯一差异：CR660X 1.0.117 stock 用 `enable_ssh` 调的是 stock 固件自带的 dropbear 配置（路径相同 `/etc/init.d/dropbear`）

## 完整流水线（6 步 + 2 工具）

```
get_router_info.sh           # 0  探测 init_info（无鉴权）
  ↓
1.official_init.py           # 工厂态→初始化（用 calc_new_pwd AES-CBC）
  ↓
2.login_get_stok.py          # 已初始化→拿 stok
  ↓
3.enable_ssh.py              # smartcontroller scene 启用 SSH
  ↓ 真 SSH 验证
4.firmware_upload_on_miwifi.sh  # scp 上传 .bin/.ubi 到 /tmp
  ↓
[未来] 5+. 烧写 + 刷 OpenWrt + 验证

工具：
- miwifi_ssh.sh               # 一键 SSH（交互 + JSON 命令模式）
- router_official_recovery.sh # 恢复出厂
```

## 验证方法（无"闭门造车"）

每写一个脚本，**必须**跑完整链路：

```bash
# 1) 恢复出厂
./router_official_recovery.sh --stok "$STOK"
# 等 90s，验证 inited=0
bash get_router_info.sh --ip 192.168.31.1 | python3 -c "import sys,json; print(json.load(sys.stdin)['inited'])"

# 2) 完整 init
python3 1.official_init.py --admin-pwd 12345678

# 3) 登录拿 stok
python3 2.login_get_stok.py --pwd 12345678

# 4) 启用 SSH
python3 3.enable_ssh.py --stok "$STOK"

# 5) 真 SSH 进去验证（关键！不是只看 TCP 22 通）
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa \
  root@192.168.31.1 'uname -a; id; cat /proc/cmdline; cat /proc/mtd | head -20'

# 6) scp 上传 + 路由器上读回验证
./4.firmware_upload_on_miwifi.sh --file /tmp/test.txt
./miwifi_ssh.sh --cmd 'cat /tmp/test.txt'
```

**关键**：第 5 步必须真 SSH 进去，**不能**只到 TCP 22 探测成功就停。

## CR 系列设计决策：不做双系统

虽然 CR6606 stock MTD 表有 `mtd6 (firmware)` + `mtd10 (firmware1)` 两个等大镜像分区（潜在双系统结构），但项目**不利用**：

- ❌ 不写 `set_miwifi_uboot_partition.sh` 切 mtd6/mtd10
- ❌ 不写 `switch_to_stock.sh` 回退 stock
- ❌ 不维护 `flag_try_sys*_failed` / `flag_boot_rootfs` 互补 flag
- ✅ 走破坏性刷机：4.official_upgrade.py 直接覆盖 mtd6
- ⚠️ 不可逆：刷 OpenWrt 后只能编程器/裸 flash 回 stock

**跟 ax6/ax3600 项目的对比**：
- ax6/ax3600：保守型双系统（保 stock 留退路）
- CR 系列：激进型破坏性刷机（一次到位，OpenWrt 即终态）

## 实测 MTD 布局（CR6606 1.0.117 stock）

```
mtd0:  00080000 "Bootloader"    mtd1:  00040000 "Nvram"      mtd2:  00040000 "Bdata"
mtd3:  00080000 "Factory"      mtd4:  00040000 "crash"      mtd5:  00040000 "crash_log"
mtd6:  01e00000 "firmware"  ←─ 主系统 (30M)              ┐
mtd7:  00340000 "kernel"                                    ├─ 同一镜像
mtd8:  01ac00000 "rootfs"                                  │
mtd9:  00e00000 "rootfs_data"                              ┘
mtd10: 01e00000 "firmware1" ←─ 备用 (30M, **不使用**)
mtd11: 03200000 "overlay"     mtd12: 01000000 "obr"
```

cmdline: `console=ttyS0,115200 firmware=0 uart_en=1 rootfstype=squashfs,jffs2`

## 协议层关键发现

| 端点 | method | 用途 | 实测 |
|------|--------|------|------|
| `/init.html` | GET | SPA 主页，引用 `init.<hash>.js` | ✅ |
| `/static/js/init.<hash>.js` | GET | KEY/IV + 密码学逻辑 | ✅ 7.6KB |
| `/cgi-bin/luci/api/xqsystem/init_info` | GET | 探测模型/状态 | ✅ |
| `/cgi-bin/luci/api/xqsystem/login` | GET | init=1 (工厂) / init=0 (已初始化) | ✅ |
| `/cgi-bin/luci/;stok=/api/xqnetwork/set_wan_new` | POST | 设 WAN | ✅ |
| `/cgi-bin/luci/;stok=/api/misystem/vas_switch` | GET | 禁更新 | ✅ |
| `/cgi-bin/luci/;stok=/api/misystem/set_router_normal` | POST | 设密码 (AES-CBC newPwd) | ✅ |
| `/cgi-bin/luci/;stok=/api/xqsystem/reset?format=0` | GET | 恢复出厂（**无** magic 字段） | ✅ |
| `/cgi-bin/luci/;stok=/api/xqsmarthome/request_smartcontroller` | POST | scene 注入 | ✅ hackCheck=0 |

## 反例（不要踩）

- ❌ 抄 `old_coding/.../flasher.py` 的 `extendwifi_connect` 注入 — xmir 日志明确 WARN
- ❌ 抄 `old_coding/.../flasher.py` 的 SHA1 newPwd — 实际是 AES-CBC
- ❌ 看到 `Server: nginx/1.12.2` 就以为是 PBoot
- ❌ 写 mtd6/mtd10 双系统切换脚本（项目决定不做）
- ❌ TCP 22 探测成功就以为 SSH 启用了（必须真 SSH 登录验证）
- ❌ 跳过 `sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear`（详见 ax6 skill）

## 参考

- 实机验证日志：`src/project/cr660x/doc/flash-pipeline.md` + `doc/troubleshooting.md`
- 项目记忆：`memory/project_cr660x_state.md` + `memory/feedback_no_aux_wifi_injection.md` + `memory/feedback_cr_no_dual_system.md` + `memory/feedback_xiaomi_ssh_scripts.md`
- 入口：`src/project/cr660x/1.official_init.py` + `2.login_get_stok.py` + `3.enable_ssh.py` + `4.firmware_upload_on_miwifi.sh` + `miwifi_ssh.sh` + `router_official_recovery.sh`
