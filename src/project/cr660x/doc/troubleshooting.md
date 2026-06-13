# CR660X — 错误排查

## [wrong_variant] 联通版用了移动版的登录方式

**现象**：登录返回 `code != 0`，或者拿不到 stok

**原因**：联通版 (`xiaomi.router.cr6606`) 和移动/电信版 (`xiaomi.router.cr6608` / `xiaomi.router.cr6609`) 登录参数不同：
- 联通版：`GET /login?init=1&privacy=1&...`，密码 `admin`
- 移动版：`POST /login` form-urlencoded，密码 `admin`

**恢复步骤**：
1. 先跑 `get_router_info.sh` 看 `model` 字段
2. 脚本根据 model 自动选 variant（无需手动）
3. 如果不识别，用 `--variant unicom|move` 强制指定

**recoverable**：true
**相关脚本**：1.official_init, 2.login_get_stok

## [inited_false] 跑 2.login 但路由器是工厂态

**现象**：`/login` 返回 `code != 0`，提示 "init=1 required" 或 "未初始化"

**原因**：工厂态 (inited=0) 路由器拒绝普通登录

**恢复步骤**：
1. 先跑 1.official_init.py 完成初始化
2. 或显式传 `--factory` 给 2.login_get_stok.py（如果支持）

**recoverable**：true
**相关脚本**：1.official_init, 2.login_get_stok

## [wrong_newpwd_crypto] 用 SHA1 算 newPwd（密码没真正改）

**现象**：set_router_normal 报 200 OK，但之后用 `admin-pwd` 登录 401；同时 `admin` 也 401 → 密码变成未知值

**原因**：`old_coding/code/src/cr660x/flasher.py` 的 `unicom_set_router_password` 用 **SHA1 哈希** 算 newPwd，这是错的。实际 JS 里的 newPwd 是 **AES-CBC** 加密。

**JS 真实逻辑**（`init.<hash>.js` 里）：
```js
oldPwd = SHA1(nonce + SHA1(old_pwd + key))                    // 明文 old_pwd
newPwd = AES-CBC(SHA1(new_pwd+key), SHA1(old_pwd+key)[:32], iv, PKCS7)
routerPwd = 明文 new_pwd
```

**正确实现**（跟 ax6/ax3600 一致）：
```python
def calc_new_pwd(old_pwd, new_pwd, key, iv):
    aes_key = bytes.fromhex(sha1_hex(old_pwd + key)[:32])
    plain = sha1_hex(new_pwd + key).encode("utf-8")
    iv_bytes = bytes.fromhex(iv)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return base64.b64encode(
        AES.new(aes_key, AES.MODE_CBC, iv_bytes).encrypt(padded)
    ).decode()
```

**恢复步骤**：
1. **重置路由器**（恢复出厂或刷回原厂固件）
2. 修脚本用 `calc_new_pwd()` 计算 newPwd
3. 重跑 1.official_init.py

**recoverable**：true（重置后重跑）
**相关脚本**：1.official_init

## [key_iv_not_found] JS 里没找到 KEY/IV

**现象**：脚本报 "JS 里未找到 key/iv 字段"

**原因**：固件版本变化导致 init.<hash>.js 里 KEY/IV 提取方式改了

**恢复步骤**：
1. 手动 `curl http://<ip>/init.html` 找 JS 文件名
2. 抓 JS 内容 `grep -oE "key[:=]..."` 看实际格式
3. 调整 `fetch_crypto_constants` 的正则

**recoverable**：true
**相关脚本**：1.official_init, 2.login_get_stok
