# AX6 初始化登录 — 密码学流程

## 概述

AX6（RA69 — IPQ8071A）出厂后首次 WEB 初始化需要用 `admin` / SHA1 双哈希登录，
算出一个 `stok` 令牌，然后用该令牌走 4 步设置向导。

所有密码学常量前端已有——路由器的 `init.html` 加载的 `init.<hash>.js` 明文包含
`key` / `iv` / `nonce` 生成 / `oldPwd` / `newPwd` / `AES` 加密全过程。
脚本在运行时抓取该 JS 提取常量和算法，不写死任何密码学值。

## 依赖

- Python 3（`urllib` / `hashlib` / `re`）
- `pycryptodome`（`Crypto.Cipher.AES`，仅用于 AES-CBC）
- 连接路由器 192.168.31.1（出厂默认 IP，未登录 HTTP）

## 初始化登录流程（4 步）

```
1. 扒 JS 提取 KEY/IV
2. 登录 (GET login → stok)
3. 设 WAN → DHCP
4. 禁自动更新
5. 设 Wi-Fi + 管理密码
```

## 密码学

### KEY / IV

**从路由器 `init.<hash>.js` 运行时扒取**——不在脚本/文档里写死任何具体值。

扒取路径：

```
文件: http://192.168.31.1/init.html
  → <script src="/static/js/init.<hash>.js">
    → grep "key\s*:\s*\"[0-9a-f]\{32\}\""   # 32-char hex
    → grep "iv\s*:\s*\"[0-9a-f]\{32\}\""
```

JS 里字段格式：

```javascript
Encrypt: {
  key: "<32-char hex>",   // SHA1 混淆密钥
  iv:  "<32-char hex>",   // AES 初始向量
  ...
}
```

| 常量 | 来源 | 类型 |
|------|------|------|
| `key` | 运行时从 `init.<hash>.js` 扒 `Encrypt.key` | 32-char hex |
| `iv`  | 运行时从 `init.<hash>.js` 扒 `Encrypt.iv` | 32-char hex |

> **设计原则**：脚本每次 init 重新扒当前固件的 JS，**不假设** KEY/IV 跨固件一致——新固件出现时自动适配。
> 文档/代码里**不固化**任何 KEY/IV 值，避免被误读为"写死常量"。

### Nonce 生成

```python
def generate_nonce() -> str:
    # frontend: Encrypt.nonceCreat()
    #           [0, this.getCookie("mac") || "", ts, rand].join("_")
    # mac = "" because no cookie before login
    ts   = int(time.time())          # 秒级时间戳
    rand = random.randint(0, 9999)   # 0-9999 随机
    return f"0__{ts}_{rand}"
```

| 字段 | 格式 | 示例 | 含义 |
|------|------|------|------|
| 前缀 | `0` | `0` | 固定版本号 |
| mac | 空字符串 | `` | 未登录前没有 cookie |
| ts | epoch 秒 | `1780928627` | 当前时间戳 |
| rand | 0-9999 随机 | `8297` | 防重放 |

> **为什么 mac 为空？** — 前端 `getCookie("mac")` 在未登录阶段返回 `null`。
> `Encrypt.nonceCreat` 用 `|| ""` 兜底。所以 nonce 三段下划线 `0__ts_rand` 是预期格式。

### 登录密码 — oldPwd

```
oldPwd = SHA1(nonce + SHA1(password + key))
```

```python
def sha1_hex(s):
    return hashlib.sha1(s.encode()).hexdigest()

def calc_login_password(nonce, password, key):
    inner = sha1_hex(password + key)     # 第 1 轮 SHA1
    return sha1_hex(nonce + inner)       # 第 2 轮 SHA1
```

| 参数 | 值 | 说明 |
|------|-----|------|
| `password` | `"admin"` | 出厂默认（固定） |
| `key` | 见上方 | 从 JS 扒 |
| 返回 | 40 字符 hex SHA1 hash | 直接拼到 URL query |

### 管理密码加密 — newPwd

```
newPwd = AES-CBC(
    plain = SHA1(new_password + key),
    key   = SHA1(old_password + key)[:32],
    iv    = IV
)
```

```python
def calc_new_pwd(old_pwd, new_pwd, key, iv):
    aes_key = bytes.fromhex(
        sha1_hex(old_pwd + key)[:32]      # 16 字节 AES key
    )
    plain   = sha1_hex(new_pwd + key).encode("utf-8")
    iv_bytes= bytes.fromhex(iv)

    pad  = 16 - (len(plain) % 16)         # PKCS7 填充
    text = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(text)
    ).decode()
```

| 步骤 | 输入 | 长度 | 输出 |
|------|------|------|------|
| 1. SHA1(old_pwd + key) | `"admin"` + key | — | 40-char hex hash |
| 2. 取前 32 字符 | (1) 的输出 | 16 字节 | AES 密钥 |
| 3. SHA1(new_pwd + key) | 用户输入的新密码 + key | 40-char hex ~= 40 字节 UTF-8 | AES 明文 |
| 4. PKCS7 补齐 | (3) 的输出 | 48 字节 (16 对齐) | 补齐明文 |
| 5. AES-CBC 加密 | (4) 的明文 + (2) 的密钥 + iv | — | 密文 |
| 6. Base64 编码 | (5) 的密文 | — | `newPwd` 字段 |

## API 详情

### 登录 API

```
GET /cgi-bin/luci/api/xqsystem/login
    ?username=admin
    &logtype=2
    &nonce=<nonce>
    &password=<oldPwd>
    &init=1
    &privacy=1
```

| 参数 | 值 | 说明 |
|------|-----|------|
| username | `admin` | 管理员用户名 |
| logtype | `2` | 登录类型（2 = GTK） |
| nonce | `0__ts_rand` | 防重放值 |
| password | `oldPwd` 40-char hex | SHA1 双哈希结果 |
| init | `1` | 标记为初始化阶段 |
| privacy | `1` | 同意隐私协议（前端 checkbox） |

**响应**:

```json
{
  "code": 0,
  "token": "e8e3a57e7bf3c..."
}
```

`token` = `stok`，一次性令牌，给后续所有 API 鉴权。

> **stok 格式**: 32 字符 hex 字符串。
> 每次登录都会生成新的 stok。一个 stok 对应一个登录会话，
> 经过几个 API 调用后不会失效，但长时间无活动可能超时。

### WAN 设置 API

```
POST /cgi-bin/luci/;stok=<stok>/api/xqnetwork/set_wan_new
    wanType=dhcp
    autoset=0
```

| 参数 | 值 | 说明 |
|------|-----|------|
| wanType | `dhcp` | 自动从上游 DHCP 获取 IP |
| autoset | `0` | 不自动设置 DNS/MAC |

### 禁用自动更新 API

```
GET /cgi-bin/luci/;stok=<stok>/api/misystem/vas_switch
    ?info=auto_upgrade%3D0
```

| 参数 | 值 | 说明 |
|------|-----|------|
| info | `auto_upgrade=0` (URL 编码) | 关闭固件自动更新 |
| stok | 登录返回 | 鉴权令牌 |

### Wi-Fi + 管理密码 API

```
POST /cgi-bin/luci/;stok=<stok>/api/misystem/set_router_normal
    name=<ssid>
    &locale=家
    &ssid=<ssid>
    &password=<wifi_pwd>
    &encryption=mixed-psk
    &nonce=<new_nonce>
    &newPwd=<calc_new_pwd>
    &oldPwd=<calc_login_password>
    &txpwr=1
    &routerPwd=<admin_pwd>
    &bw160=false          ← 仅固件 ≥ 1.1.x 时携带
```

| 字段 | 值 | 说明 |
|------|-----|------|
| name | ssid 或 router 返回 | Wi-Fi SSID 名称 |
| locale | `家` | 地区 |
| ssid | 同上 | 重复 name（前端一致） |
| password | Wi-Fi 密码（用户输入）| 新 Wi-Fi 密码 |
| encryption | `mixed-psk` | WPA2+WPA3 混合加密 |
| nonce | 新的 nonce | 防重放 |
| newPwd | `calc_new_pwd("admin", admin_pwd)` | 管理密码被 AES 加密 |
| oldPwd | `calc_login_password(nonce, "admin")` | 当前密码（admin）的 hash |
| txpwr | `1` | 发射功率（自动） |
| routerPwd | admin_pwd | 管理密码（明文） |
| bw160 | `false` | 关闭 160MHz 5GHz 带宽 |

### bw160 字段的版本自适应

| 固件版本 | 是否携带 `bw160=false` | 理由 |
|---------|----------------------|------|
| `1.0.x` | ❌ 不携带 | 1.0.x 固件后端不识别该字段，多传 = 参数错误 |
| `1.1.x` | ✅ 携带 | 小米 1.1.0 起引入 160MHz 控制字段，init 阶段固定 `false` |

```python
def need_bw160(version):
    """固件版本 >= 1.1 需要 bw160=false"""
    major, minor = (int(x) for x in version.split(".")[:2])
    return (major, minor) >= (1, 1)
```

> **来源**: `old_coding/Auto_Flash_Router/AX6/auto_init.py` 注释。
> **1.0.x 行为**: 未实测 — 无法在当前设备上验证。
> 注释称 "1.0.x 不能带此字段"。

## 前端 JS 对比

| 前端 (init.js Encrypt) | Python 复刻 (1.official_init.py) | 
|----------------------|------------------------------|
| `init()` — nonceCreat → 存 this.nonce | `generate_nonce()` — 返回字符串 |
| `oldPwd("admin")` — SHA1(pwd+key) | `calc_login_password(nonce, pwd, key)` — 双 SHA1 |
| `newPwd(old, new)` — AES-CBC | `calc_new_pwd(old, new, key, iv)` — 一字不差 |
| `p.AES.encrypt(...)` — CryptoJS 库 | `Crypto.Cipher.AES` — pycryptodome |

两者等价。同一套 key/iv 下，前端登录和新脚本登录获取的 stok 完全相同。

## 示例

```bash
# 实例化初始化
python3 1.official_init.py --admin-pwd 12345678

# 输出（stderr 日志）
[INFO] 扒取前端 JS 提取 KEY/IV
[INFO] 使用路由器返回的 SSID: Redmi_0BA0_F45F
[INFO] 固件 1.1.17, bw160=True
[INFO] 登录成功
[INFO] WAN 已设为 DHCP
[INFO] 已禁用自动更新
[INFO] Wi-Fi 与管理密码设置完成

# 输出（stdout JSON）
{"ok": true, "step": "official_init", "data": {
  "stok": "5bbdf98888a4fb8af5566dd926dea20b",
  "ip": "192.168.31.1",
  "ssid": "Redmi_0BA0_F45F",
  "firmware_version": "1.1.17",
  "key_source": "fetched from init.<hash>.js"
}}
```

## 参考

- `old_coding/Auto_Flash_Router/AX6/auto_init.py` — 原始参考实现
- `old_coding/Auto_Flash_Router/AX6/QWEN.md` — 漏洞原理 / SSH 开启
- `/tmp/init.js` — 前端 Encrypt 模块（运行时抓取）
- `chunk_14.js` — 前端 loginInfo / routerInfo 实现
- `chunk_4.js` — 前端 setRouterNormal 实现
