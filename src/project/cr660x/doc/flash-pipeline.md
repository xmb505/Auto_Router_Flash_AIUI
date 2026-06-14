# CR660X — 刷机流水线

> ⚠️ **2026-06-14 标记：SSH 破解方法不通用。** 
> smartcontroller scene 注入（CVE-2023-26319）只在部分固件版本/运营商定制上可用。
> **在确认具体版本可用之前，不再推进 CR660X 编排器开发。**
> 如需刷机，请按各步骤脚本手动调试。

> CR660X 是小米/红米路由器系列（CR6606/TR606 联通 / CR6608/TR608 移动 / CR6609/TR609 电信）。当前是 **stock 固件**（未刷 pb-boot/breed），HTTP 服务是 stock 自带的 nginx/1.12.2。
> init_info API 跟 ax6/ax3600 完全一致，KEY/IV 一样，密码学一样，**剥壳后流程跟 ax6 同结构**。

## 已完成步骤

| # | 脚本 | 状态 |
|---|------|------|
| 0 | `get_router_info.sh` | ✅ 实测 |
| 1 | `1.official_init.py` | ✅ 实测 |
| 2 | `2.login_get_stok.py` | ✅ 实测 |
| 3 | `3.enable_ssh.py` | ⚠️ **SSH 方法不通用，待确认** |
| 4 | `4.firmware_upload_on_miwifi.sh` | ✅ 实测 (scp 上传 + 真读到文件) |
| 5 | `5.uboot_write_in_miwifi.py` | ✅ 实测 (mtd unlock + mtd write /dev/mtd0) |
| 6 | `6.openwrt_write_in_miwifi.py` | ✅ 实测 (sysupgrade -F initramfs, 路由器自动重启) |
| 7 | `7.firmware_upload_on_openwrt.py` | ✅ 已实现 (scp 上传 sysupgrade + SSH sysupgrade -F 烧持久 rootfs) |
| - | `miwifi_ssh.sh` | ✅ 实测 (uname/cat banner 跑通) |
| - | `router_official_recovery.sh` | ✅ 实测 (恢复出厂) |
| - | `openwrt_modern_standard_ssh.sh` | ✅ 已实现|

## 全链路状态

**当前状态**：3.enable_ssh.py 的 smartcontroller scene 注入**不通用**，部分固件/运营商定制版不可用。
在确认通用破解方法前，暂停编排器开发。

## 刷机流程

### 入口：先看机型

```
              get_router_info.sh
              看 model 字段
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
    CR6606 / TR606（联通）     CR6608 / TR608（移动） / TR609（电信）
    inited=1, 密码未知     贴纸密码大概率没改
         │                     │
   ┌─────┴─────┐         ┌────┴────┐
   ▼           ▼         ▼         ▼
知道密码？  不知道    试贴纸密码  试了不对
（不可能） 物理 Reset  ─── 登录成功   物理 Reset
               │            │           │
         1.official_init     │     1.official_init
         （设新密码）        │     （设新密码）
               │            │           │
         2.login_get_stok    │     2.login_get_stok
               │            │           │
               └── 3.enable_ssh.py ─────┘
                    │
              4. scp 上传 pb-boot.img
                    │
              5. mtd write /dev/mtd0
                    │
              4. scp 上传 initramfs-kernel.bin
                    │
              6. sysupgrade -F initramfs → 重启
                    │
              7. scp + sysupgrade -F 正式固件 → 完成
```

### 为什么 CR6606 没有"直接登录"路径

CR6606（联通版）出厂有初始化向导（`/cgi-bin/luci/api/xqsystem/login?init=1&privacy=1`），
上电后用户必须走完初始化才能用路由器。密码是用户设的，不是贴纸上的。
**你拿到的 CR6606 一定是已被初始化过的**，密码你不知道，也无法从包装得知。

→ 只能**物理 Reset**（按住 RESET 键上电）回到 inited=0，然后 `1.official_init.py` 设新密码。

### 物理 Reset 方法

路由器通电状态下，用卡针按住 RESET 孔保持 5-10 秒，指示灯闪烁后松手。
路由器会自动重启回到工厂态（inited=0，管理密码恢复 `admin`）。

**不能用 `router_official_recovery.sh`**——那个 API 需要 stok，拿 stok 需要密码，死锁。

### CR6608 / TR609 入口

CR6608（移动版）和 TR609（电信版）出厂**自动初始化**，recovery 后也会自动初始化。

> ⚠️ **贴纸上的 8 位无线密码（Wi-Fi 密码）不是管理密码**，两者是分开的。
> 人类工人易混淆，不知道管理密码时不要猜，直接物理 Reset。

```bash
# 1. 找 IP
./check_cr660x_ip_online.sh

# 2. 如果你知道管理密码，直接登录
python3 2.login_get_stok.py --ip <IP> --pwd <管理密码>

# 如果不知道密码或返回 code != 0 → 物理 Reset 后走 1.official_init.py
```

### 刷机步骤（CR6608/TR609 标准路径，知道管理密码时）

```bash
# 0. 找 IP
./check_cr660x_ip_online.sh

# 1. 登录拿 stok
./get_router_info.sh --ip <IP>
python3 2.login_get_stok.py --ip <IP> --pwd <管理密码>

# 2. 开 SSH（smartcontroller scene 注入 CVE-2023-26319，给足 240s）
timeout 240 python3 3.enable_ssh.py --ip <IP> --stok <stok>

# 3. 上传 pb-boot + initramfs，写 uboot + 烧 initramfs
./4.firmware_upload_on_miwifi.sh --ip <IP> --file files/pb-boot.img
python3 5.uboot_write_in_miwifi.py --ip <IP> --file pb-boot.img
./4.firmware_upload_on_miwifi.sh --ip <IP> --file files/initramfs-kernel.bin
python3 6.openwrt_write_in_miwifi.py --ip <IP> --file initramfs-kernel.bin

# 4. 等路由器重启进 initramfs OpenWrt (192.168.1.1)，烧正式固件
python3 7.firmware_upload_on_openwrt.py --file files/immortalwrt-*-sysupgrade.bin
```

### 刷机步骤（CR6606 标准路径）

```bash
# 0. 找 IP
./check_cr660x_ip_online.sh

# 1. 物理 Reset → 等重启 → 工厂态 (inited=0)

# 2. 初始化并登录
python3 1.official_init.py --ip <IP> --admin-pwd <新密码>
python3 2.login_get_stok.py --ip <IP> --pwd <新密码>

# 2. 开 SSH（同 CR6608）
timeout 240 python3 3.enable_ssh.py --ip <IP> --stok <stok>

# 3-5. 上传 + 刷入（完全一样）
./4.firmware_upload_on_miwifi.sh --ip <IP> --file files/pb-boot.img
python3 5.uboot_write_in_miwifi.py --ip <IP> --file pb-boot.img
./4.firmware_upload_on_miwifi.sh --ip <IP> --file files/initramfs-kernel.bin
python3 6.openwrt_write_in_miwifi.py --ip <IP> --file initramfs-kernel.bin

# 6. 等重启后烧正式固件
python3 7.firmware_upload_on_openwrt.py --file files/immortalwrt-*-sysupgrade.bin
```

## 决策树

```
               get_router_info.sh → model 字段
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
       CR6606 / TR606          CR6608 / TR608
       （联通）                 （移动）
       inited=1, 密码未知       CR6609 / TR609（电信）
            │                  管理密码未知 / 有人知道有人不知道
            │                       │
       物理 Reset               ┌────┴────┐
       （不能用 API recovery）  知道密码？  不知道
            │                  ──登录成功── 物理 Reset
       1.official_init.py          │          │
            │                      │    1.official_init.py
       2.login_get_stok.py         │          │
            │                      │    2.login_get_stok.py
            └────── 3.enable_ssh.py ─────────┘
                        │
                  4. scp pb-boot.img
                        │
                  5. mtd write /dev/mtd0
                        │
                  4. scp initramfs-kernel.bin
                        │
                  6. sysupgrade -F → 重启进 initramfs
                        │
                  7. scp + sysupgrade -F 正式固件 → 完成
```

**物理 Reset**：按住 RESET 孔 5-10 秒上电。不能用 `router_official_recovery.sh`（死锁：要 stok → 要密码 → 不知道）。

## Variant 判别

| model 字段 | 硬件 | 行为 |
|------------|------|------|
| `xiaomi.router.cr6606` | CR6606 / TR606 | 联通版：无密码，必须物理 Reset；GET init=1 |
| `xiaomi.router.cr6608` | CR6608 / TR608 | 移动版：管理密码不一定知道，不知道就走物理 Reset |
| `xiaomi.router.cr6609` | CR6609 / TR609 | 电信版 |
| 未知 | 默认按移动版流程 + reason=variant_unknown |

> 💡 **冷知识**：CR6606/TR606、CR6608/TR608、CR6609/TR609 硬件完全相同（MT7621A），只是运营商定制固件不同。刷入 OpenWrt 后都报告为 CR6608。

## stock 固件协议（实测 2026-06-11）

> 注：这一节描述的是 **stock 小米固件自带**的 HTTP/init API，**不**是任何第三方 bootloader（pb-boot/breed）的协议。
> 我们的脚本（1.official_init / 2.login_get_stok / 3.enable_ssh）只跟这层 API 交互，跟 bootloader 无关。

| 端点 | method | 用途 |
|------|--------|------|
| `GET /init.html` | GET | SPA 主页，引用 `init.<hash>.js` |
| `GET /static/js/init.<hash>.js` | GET | 含 KEY/IV + 密码学逻辑 |
| `GET /cgi-bin/luci/api/xqsystem/init_info` | GET | 探测模型/状态/romversion |
| `GET /cgi-bin/luci/api/xqsystem/login` | GET | 工厂态：init=1&privacy=1 |
| `GET /cgi-bin/luci/api/xqsystem/login` | GET | 已初始化：init=0 |
| `POST /cgi-bin/luci/;stok=<token>/api/xqnetwork/set_wan_new` | POST | 设 WAN |
| `GET /cgi-bin/luci/;stok=<token>/api/misystem/vas_switch?info=auto_upgrade=0` | GET | 禁更新 |
| `POST /cgi-bin/luci/;stok=<token>/api/misystem/set_router_normal` | POST | 设 Wi-Fi/管理密码 |

## 密码学（JS 反推，2026-06-11）

```js
// init.<hash>.js 里的 newPwd/oldPwd 计算（联通版 set_router_normal）
oldPwd = SHA1(nonce + SHA1(old_pwd + key))                       // 明文 old_pwd
newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7)  // base64
routerPwd = 明文 new_pwd
```

**关键发现**：`encrypt(i, n, {iv, mode:CBC, padding:Pkcs7})` 出现在 JS 里 → **必须用 AES-CBC** 算 newPwd。
**不要照搬 `old_coding/code/src/cr660x/flasher.py`**——它用的是简单 SHA1 哈希，是错的（会导致密码没真正改）。

**实机验证**（2026-06-11）：
- 1.0.117 stock 固件，model=CR6606
- 扒 KEY=`a2ffa5c9...` / IV=`64175472...`
- set_router_normal 用 AES-CBC 算 newPwd → 成功
- 用新密码（newpass123）登录 → stok 拿到

**跟 ax6/ax3600 算法完全一致**——小米体系共享这套密码学。

## 已知固件

- **Stock CR6606 1.0.117**（联通版带小米云）— 已实测
- **Stock CR6608 1.0.100**（移动版）— 已实测，2026-06-11 可复现破解
- **OpenWrt 官方**：`ramips/mt7621` target，需移植
- **ImmortalWrt**（mt7621）
- **pb-boot (PandoraBox uboot)** — **第三方** bootloader，写入 mtd0 后由它接管引导

## CR6608 1.0.100 破解记录（2026-06-11，同硬件 TR608 同理）

### 唯一可用路径

| 漏洞 | 端点 | 响应 |
|------|------|------|
| ✅ smartcontroller scene (CVE-2023-26319) | `xqsmarthome/request_smartcontroller` | `scene_setting`/`scene_start_by_crontab` 正常 |
| ❌ set_config_iotdev -h 注入 | `misystem/set_config_iotdev` | `code:1523` |
| ❌ c_upload + netspeed XML 注入 | `misystem/c_upload` | `code:1629` |
| ❌ arn_switch / start_binding / set_mac_filter / datacenter7 | 各自 | 不执行 |

### 可复现流程（CR6608 1.0.100 实机验证 2026-06-11，贴纸密码未改时用）

```bash
# 0. 找 IP
./check_cr660x_ip_online.sh

# 1. 试贴纸密码登录
python3 2.login_get_stok.py --ip 192.168.10.1 --pwd <贴纸密码>

# 2. 开 SSH（必须 240s 超时——exec_cmd 分块注入很慢）
timeout 240 python3 3.enable_ssh.py --ip 192.168.10.1 --stok <stok>

# 3. 验证 SSH
sshpass -p root ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.10.1 "id"
# uid=0(root) gid=0(root)

# 4. 刷机（以上游步骤 4-7 全自动）
```

> 如果贴纸密码不对（code != 0）：物理 Reset → 回到 inited=0 → `1.official_init.py` 设新密码 → 继续。

### 关键注意事项

- **不需要恢复出厂**：大部分人不会改密码，贴纸密码直接登录即可。恢复出厂仅在忘记密码时用。
- **移动版自动初始化** → `inited` 永远为 1，跳过 step 1
- `get_scene_setting` 返回 `code:-100` **不影响注入**——场景创建和触发是独立接口
- **必须跑热身**：直接 `scene_setting` 不生效，要先 `set_sys_time` 写 `/tmp/ntp.status` 唤醒 smartcontroller
- **timeout 至少 240s**：`exec_cmd` 分块注入 3 条命令需要 ~120s 纯执行时间 + TCP 探测 ~30s
