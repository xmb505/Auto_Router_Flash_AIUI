---
name: openwrt-ubus-jsonrpc-auth
description: 逆向 OpenWrt/LEDE ubus JSON-RPC 认证机制（非小米体系），获取 ubus_rpc_session 并利用管理 API
source: auto-skill
extracted_at: '2026-06-13T08:50:00.000Z'
---

# OpenWrt/LEDE ubus JSON-RPC 认证逆向

某些路由器（Newifi/Lecoo/PandoraBox 等）基于 OpenWrt/LEDE 但使用定制 SPA（通常为 AngularJS），其 API 体系是 **JSON-RPC 2.0 over HTTP POST /ubus**，与小米的 stok/AES 体系完全不同。

## 1. 发现 API 端点

```bash
# 列出所有可用的 RPC 对象（匿名可调）
curl -s -X POST http://<router-ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"list"}'

# 返回示例：
# {"jsonrpc":"2.0","result":["session","system","uci","xapi.basic",...]}
```

常见可用对象：`session`, `system`, `uci`, `network`, `xapi.basic`, `xapi.*`

## 2. 查找登录机制

从前端 JS 文件中定位登录函数。在 Newifi/Lecoo 的 Angular SPA 中：

**关键线索**（搜索前端 JS）：
```javascript
// 找 xapi_login 或 session.login 调用
L.session.login(u, p)
// 找 base64 编码
$.base64("encode", p)
// 找 session token
response.ubus_rpc_session
L.globals.sid = response.ubus_rpc_session
```

**常见位置**：
- `/<resource>/ui.js` — 登录状态机（`L.ui.login`）
- `/<resource>/session.js` — 登录 RPC 声明
- `/<resource>/newifi.js` — 全局配置（含默认 `sid`）

## 3. 关键发现点

### 用户名
前端 JS 经常**硬编码**用户名，不是从表单读取：
```javascript
var u = "root";  // ← 写死的！不是 "admin"
```

### 密码编码
密码通常经过编码再发送。常见模式：
- **base64**（Newifi/Lecoo）：`$.base64("encode", p)`
- 直接明文（某些系统）

### Token 名称
成功后返回的会话令牌叫 **`ubus_rpc_session`**（32 位 hex 字符串）：
```json
{
  "result": [0, {
    "ubus_rpc_session": "424b4a1d93fcf104c5731851542f05fd",
    "timeout": 300
  }]
}
```

## 4. 登录实战

```bash
# 1) base64 编码密码
PWD=$(echo -n "12345678" | base64)

# 2) 登录（username 通常是 "root" 或 "admin"）
LOGIN_RESP=$(curl -s -X POST http://192.168.99.1/ubus \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0", "id":1, "method":"call",
    "params":[
      "00000000000000000000000000000000",
      "session", "xapi_login",
      {"username":"root", "password":"'"$PWD"'"}
    ]
  }')

# 3) 提取 ubus_rpc_session
SID=$(echo "$LOGIN_RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d['result'][1]['ubus_rpc_session'])
")

echo "SID=$SID"
```

**注意**：登录请求中的 `sid` 参数（第一个数组元素）用匿名 ID `"00000000000000000000000000000000"`（全零 32 位 hex）。

## 5. 使用 Token 调管理 API

把匿名 sid 替换为真实的 `ubus_rpc_session`：

```bash
# 调用 system.board（需要认证）
curl -s -X POST http://192.168.99.1/ubus \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0", "id":1, "method":"call",
    "params":["'"$SID"'", "system", "board", {}]
  }'

# 调用 uci get
curl -s -X POST ... \
  -d '{"params":["'"$SID"'", "uci", "get",
       {"config":"system","section":"@system[0]","option":"hostname"}]}'
```

## 6. 常见管理 API

登录后可访问的典型管理接口（需 `ubus_rpc_session`）：

| 方法 | 功能 |
|------|------|
| `system.board` | 硬件/固件信息 |
| `system.info` | 系统状态（内存、负载、运行时间） |
| `uci.get` | 读取配置 |
| `uci.set` | 修改配置 |
| `uci.commit` | 提交配置 |
| `network.interface.wan.status` | WAN 状态 |
| `network.interface.lan.status` | LAN 状态 |
| `network.wireless.status` | WiFi 状态 |
| `xapi.basic.*` | 厂商扩展 API |

## 7. 开 SSH 的路径

不同固件开 SSH 的 API 不同。搜索前端 JS 中的关键词：

```bash
# 从前端 JS 搜索 SSH/root/dropbear 关键词
curl -s http://<ip>/<resource>/*.js | grep -oE '.{0,50}(ssh|dropbear|root|telnet).{0,50}'
```

Newifi/Lecoo 已验证：
- **API**: `xapi.basic.open_dropbear`
- **调用**：`{"params":["$SID", "xapi.basic", "open_dropbear", {}]}`
- **返回**: `{"result":[0,{"status":0}]}` → SSH 22 端口立即可达

## 8. 初始化状态检测与恢复出厂

部分 Newifi/PandoraBox 固件提供无需认证的初始化状态检测 API：

### 检测是否已初始化

```bash
curl -s -X POST http://<ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0", "id":1, "method":"call",
    "params":["00000000000000000000000000000000",
              "xapi.basic", "get_guide_status", {}]
  }'
# status=0 → 未初始化（刚恢复出厂）
# status=1 → 已初始化（需密码登录）
```

### 恢复出厂设置

```bash
curl -s -X POST http://<ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0", "id":1, "method":"call",
    "params":["$SID", "xapi.basic", "reset_start", {}]
  }'
# 调用后路由器立即进入重置流程，HTTP 断连是预期行为
```

### 初始化（设置管理密码）

未初始化时，先用默认密码登录（出厂默认可能是空密码或 "admin"），然后设置新密码：

```bash
# 1) 用默认密码登录获取临时 SID
PWD_B64=$(echo -n "" | base64)  # 或 "admin"
LOGIN_RESP=$(curl -s -X POST http://<ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"call",
       "params":["00000000000000000000000000000000",
                 "session","xapi_login",
                 {"username":"root","password":"'"$PWD_B64"'"}]}')
SID=$(echo "$LOGIN_RESP" | python3 -c "
import sys,json; d=json.load(sys.stdin);
print(d['result'][1]['ubus_rpc_session'])
")

# 2) 设置新密码（base64 编码 old/new/confirm）
OLD_B64=$(echo -n "" | base64)    # 原密码
NEW_B64=$(echo -n "12345678" | base64)  # 新密码
curl -s -X POST http://<ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"call",
    "params":["'"$SID"'", "xapi.sys", "set_login_passwd_base64",
              {"old":"'"$OLD_B64"'","new":"'"$NEW_B64"'",
               "confirm":"'"$NEW_B64"'"}]
  }'
```

**⚠️ 关键陷阱**：设置新密码后，旧密码的 session（sid）会被销毁。所以 init 流程中返回的 sid **不能再用于后续操作**。必须用新密码重新登录拿新 sid：

```bash
# 设置完密码后，必须重新登录！
PWD_B64=$(echo -n "12345678" | base64)
curl -s -X POST http://<ip>/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"call",
       "params":["00000000000000000000000000000000",
                 "session","xapi_login",
                 {"username":"root","password":"'"$PWD_B64"'"}]}'
```

## 9. Token 生命周期

- 超时：默认 **300 秒（5 分钟）**
- 每次登录生成**新 token**，旧 token 立即失效
- 设置密码后，旧密码对应的 token 立即销毁
- 每次调用 API 刷新超时计时
- 无 Cookie 机制，纯参数传递

## 10. 与小米体系对比

| 维度 | 小米 (stok) | OpenWrt ubus |
|------|------------|--------------|
| 协议 | HTTP REST `/cgi-bin/luci/;stok=xxx/api/...` | JSON-RPC 2.0 `POST /ubus` |
| Token 名 | `stok` | `ubus_rpc_session` |
| 密码编码 | SHA1→AES-CBC | base64（有时明文） |
| 用户名 | `admin` | 前端硬编码，多见于 `root` |
| 传递方式 | URL path | JSON body `sid` 字段 |
| 超时 | 多种（页面/js会话） | 5 分钟硬超时 |
| Cookie | 不需要 | 不需要 |
