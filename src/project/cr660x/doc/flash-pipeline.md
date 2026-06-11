# CR660X — 刷机流水线

> CR660X 是小米/红米路由器系列（CR6606 联通 / CR6608 移动电信 / CR6609 越南）。当前是 **stock 固件**（未刷 pb-boot/breed），HTTP 服务是 stock 自带的 nginx/1.12.2。
> init_info API 跟 ax6/ax3600 完全一致，KEY/IV 一样，密码学一样，**剥壳后流程跟 ax6 同结构**。

## 已完成步骤

| # | 脚本 | 状态 |
|---|------|------|
| 0 | `get_router_info.sh` | ✅ 实测 |
| 1 | `1.official_init.py` | ✅ 实测 |
| 2 | `2.login_get_stok.py` | ✅ 实测 |
| 3 | `3.enable_ssh.py` | ✅ 实测 (hackCheck=0, scene 链路通, 真 SSH 进 root) |
| 4 | `4.firmware_upload_on_miwifi.sh` | ✅ 实测 (scp 上传 + 真读到文件) |
| - | `miwifi_ssh.sh` | ✅ 实测 (uname/cat banner 跑通) |
| - | `router_official_recovery.sh` | ✅ 实测 (恢复出厂) |

## 决策树

```
                 [init_info: inited?]
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
           inited=0                inited=1
          (工厂态)                (已初始化)
              │                       │
    1.official_init.py        2.login_get_stok.py
              │                       │
              └───────────┬───────────┘
                          ▼
                  [stok + ip + variant]
```

## Variant 判别

| model 字段 | 硬件 | 行为 |
|------------|------|------|
| `xiaomi.router.cr6606` | CR6606 | 联通版：GET init=1, 密码 admin |
| `xiaomi.router.cr6608` | CR6608 | 移动/电信版：POST form-urlencoded |
| 其他 | 未知 | 默认按移动版流程 + reason=variant_unknown |

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

- **Stock CR6606 1.0.117**（联通版带小米云）— 当前状态
- **OpenWrt 官方**：`ramips/mt7621` target，需移植
- **ImmortalWrt**（mt7621）
- **pb-boot (PandoraBox uboot)** — **第三方** bootloader，写入 mtd0 后由它接管引导
