---
name: xiaomi-js-crypto-reverse-engineer
description: 当 old_coding/ 里的 newPwd/oldPwd 算法可能写错时，从 init.<hash>.js 反推 AES-CBC 算法（适用于 ax6/ax3600/cr660x 等小米体系路由器）
source: auto-skill
extracted_at: '2026-06-11T10:59:19.893Z'
---

# 小米路由器 newPwd 算法反推 — 从 init.<hash>.js 提取 AES-CBC

## 适用场景

- 迁移 `old_coding/.../<机型>/` 到 `src/project/<机型>/` 时
- 老脚本里 newPwd/oldPwd 的算 hash 逻辑存疑
- 实机测试发现密码**没真正改**（admin 也不对、newpass123 也不对）
- 想验证当前 Python 实现的 `calc_new_pwd` 是否与小米体系一致

**历史教训**：CR660X 第一次写 `1.official_init.py` 时照搬 `old_coding/code/src/cr660x/flasher.py` 的 SHA1 哈希算 newPwd，结果 set_router_normal 返 200 但密码没改。**深扒 JS 才看到真实算法是 AES-CBC**。这跟 ax6/ax3600 一致——小米共享这套密码学。

## 单一真理源：`init.<hash>.js`

**永远不要相信老 Python 代码里的密码学实现**。JS 才是 single source of truth。

`init.html` 引用的 `init.<hash>.js` 里一定包含 KEY/IV 字段和 `encrypt`/`decrypt` 函数调用。扒 JS 找密码学签名比读老 Python 可靠得多——老 Python 可能没跑过（错算法写在那里），JS 是浏览器实际跑过的。

## 5 步反推流程

### 1. 抓 `init.<hash>.js`

```bash
IP=192.168.31.1
jsname=$(curl -s "http://$IP/init.html" | grep -oE "init\.[a-f0-9]+\.js" | head -1)
curl -s "http://$IP/static/js/$jsname" -o /tmp/init.js
echo "size: $(wc -c < /tmp/init.js) bytes"
```

### 2. 抓 KEY/IV

```bash
grep -oE "key\s*[:=]\s*['\"][0-9a-f]{32}['\"]" /tmp/init.js
grep -oE "iv\s*[:=]\s*['\"][0-9a-f]{32}['\"]" /tmp/init.js
# 输出样例 (小米共享):
# key:"a2ffa5c9be07488bbb04a3a47d3c5f6a"
# iv :"64175472480004614961023454661220"
```

### 3. 抓 newPwd/oldPwd 实现（最关键）

```bash
# 找 password 校验函数（新 PWD 强度检查，无关）— 排除
# 找 newPwd/oldPwd 的实现 — 关键
python3 << 'EOF'
content = open('/tmp/init.js').read()
# 找完整 newPwd 函数字串（300 字符够看）
import re
m = re.search(r'newPwd:function\([^)]+\)\{.{0,500}\}', content)
if m:
    print(m.group(0))
EOF
```

**期望看到的模式**（ax6/ax3600/cr660x 通用）：

```js
oldPwd: function(t) {
  return SHA1(this.nonce + SHA1(t + this.key).toString()).toString()
},
newPwd: function(t, e) {  // t=oldPwd 明文, e=newPwd 明文
  var n = SHA1(t + this.key).toString()        // n = SHA1(oldPwd+key).hex
  n = (n = enc.Hex.parse(n).toString()).substr(0, 32)  // 截前 32 hex (16 字节)
  n = enc.Hex.parse(n)                          // 16 字节 AES key
  var i = SHA1(e + this.key).toString()        // i = SHA1(newPwd+key).hex (40 字节明文)
  var o = enc.Hex.parse(this.iv)                // o = 16 字节 IV
  return AES.encrypt(i, n, {
    iv: o, mode: CBC, padding: Pkcs7
  }).toString()                                 // base64 输出
}
```

**关键标记**：`encrypt(i, n, {iv, mode:CBC, padding:Pkcs7})` 一出现，必是 AES-CBC。

### 4. 验证老 Python 代码是否一致

如果老 Python 代码是这样的：

```python
# ❌ 错的（来自 old_coding flasher.py）
new_pwd_hash = SHA1(nonce + SHA1(new_pwd + key))  # 不是 AES，只是 SHA1
```

对照 JS 看到的 `AES.encrypt(i, n, {iv, mode:CBC, padding:Pkcs7})`：
- 算法不一致
- 直接照搬会导致密码没真正改
- 必须用 AES-CBC 实现

### 5. 用 Python 实现（跨 ax6/ax3600/cr660x 通用）

```python
import base64, hashlib
from Crypto.Cipher import AES

def calc_new_pwd(old_pwd: str, new_pwd: str, key: str, iv: str) -> str:
    """newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7)
    
    JS 映射：
      n = SHA1(old_pwd + key).hex[:32]    // 16 字节 AES key
      i = SHA1(new_pwd + key).hex          // 40 字节明文
      o = hex2bin(iv)                       // 16 字节 IV
      return base64(AES-CBC-encrypt(i, n, {iv:o, CBC, Pkcs7}))
    """
    aes_key = bytes.fromhex(hashlib.sha1((old_pwd + key).encode()).hexdigest()[:32])
    plain = hashlib.sha1((new_pwd + key).encode()).hexdigest().encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()
```

oldPwd 用法（不同方向，参见 `step-script-migrate-from-old` 的 4b 决策表）：

```python
# 工厂态 init 时的 oldPwd（明文 "admin"）
old_pwd_hash = SHA1(nonce + SHA1("admin" + key))

# 已初始化后 set_router_normal 时的 oldPwd（仍是明文 "admin"）
old_pwd_hash = SHA1(nonce + SHA1("admin" + key))
```

## 验收清单

- [ ] 从 JS 看到 `AES.encrypt(i, n, {iv, mode:CBC, padding:Pkcs7})` → 用 AES-CBC 实现
- [ ] 没有看到 `encrypt(...CBC...)` → 老 Python 的 SHA1 可能是对的（如最早期固件）
- [ ] 实机验证：用新密码能登录 + 旧密码不能登录

## 跨机型一致性

| 机型 | JS 里 encrypt(...CBC...) | newPwd 算法 | 实测 |
|------|--------------------------|-------------|------|
| ax6 (RA69 IPQ8071A) | ✅ | AES-CBC | ✅ |
| ax3600 (R3600 IPQ8071A) | ✅ | AES-CBC | ✅ |
| cr660x (CR6606 MT7621) | ✅ | AES-CBC | ✅ 2026-06-11 |

KEY = `a2ffa5c9be07488bbb04a3a47d3c5f6a`（小米共享）  
IV = `64175472480004614961023454661220`（小米共享）  
**任何小米体系路由器，只要看到这 KEY + IV + JS 里有 AES-CBC 调用 → newPwd 算法一致**。

## 同步要做的

- 把"反推结果"写进 `doc/<机型>/flash-pipeline.md`（密码学段）
- 把已知错误（如 `[wrong_newpwd_crypto]`）加进 `doc/<机型>/troubleshooting.md`
- 校对 `calc_new_pwd` 函数实现，确保不抄错
- 跑实机：set_router_normal 200 OK + 用新密码能登录（不是 admin 也不是 old 密码）
