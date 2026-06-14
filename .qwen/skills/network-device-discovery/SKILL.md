---
name: network-device-discovery
description: 探测未知路由器 IP 的 HTTP API 来识别型号、固件类型、初始化状态和可达端口——从零发现而不是依赖已知漏洞路径
source: auto-skill
extracted_at: '2026-06-13T08:27:29.833Z'
---

# 网络设备发现与固件识别方法

## 适用场景

拿到一个未知 IP（如 `192.168.99.1`）时，需要回答三个问题：
1. 这是什么路由器/设备？（品牌、型号、固件）
2. 当前在什么状态？（初始化/未初始化/刷机后滞留）
3. 有什么接口可用？（HTTP/SSH/Telnet/API）

**不假设品牌**——从零探测。适合 Newifi、小米、OpenWrt、Padavan 等多种固件。

## 步骤总览

1. **端口扫描** — 发现开放的服务端口
2. **HTTP 指纹识别** — 从首页 HTML/header 判断固件类型
3. **API 协议发现** — 如果支持 ubus/JSON-RPC，用 list 方法枚举所有对象
4. **匿名权限探测** — 哪些 API 无需认证就能调
5. **初始化状态判定** — 通过模板文件存在性 + API 返回模式判断
6. **登录测试** — 尝试常见默认密码

---

## 1. 端口扫描

```bash
# 快速扫描关键端口
for port in 22 23 80 443 8080; do
  nc -zv -w3 <IP> $port 2>&1 && echo "OPEN: $port" || echo "CLOSED: $port"
done
```

## 2. HTTP 指纹识别

### 响应头检查

```bash
curl -s -i http://<IP>/ | head -30
```

关键信号：

| 信号 | 可能的固件 |
|------|-----------|
| `Server: uhttpd` | OpenWrt / PandoraBox / LuCI |
| `Server: nginx` | 小米 stock（较新版本） |
| `Server: lighttpd` | Padavan / PandoraBox（老版本） |
| `Server: Breed/1.0` | **breed 恢复模式**（bootloader 层） |
| `x-luci-login-required: yes` | OpenWrt LuCI |
| Angular SPA (`ng-app='newwifi'`) | **Newifi/PandoraBox stock** |
| `ng-app='xq-front'` | **小米/Redmi stock** |
| `title: Lecoo` | Lecoo（联想）Newifi |
| `title: 小米路由器` / `Redmi 路由器` | 小米/Redmi stock |

### 关键检查点清单

```bash
# 1. 首页 - 最快速的品牌识别
curl -s http://<IP>/ | grep -oE '<title>[^<]+</title>' 

# 2. breed 模式检测（bootloader，非完整系统）
curl -s http://<IP>/index.html | grep -i breed

# 3. 常见路径探测
for path in /cgi-bin/luci /newifi /ubus /api /api/misystem /cgi-bin; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://<IP>$path)
  echo "$code $path"
done

# 4. JS 特征 - 提取前端框架路径
curl -s http://<IP>/ | grep -oE 'src="[^"]+\.js"' | head -5
```

## 3. JSON-RPC (ubus) API 发现

很多基于 OpenWrt/LuCI 的固件（包括 Newifi、小米、PandoraBox）使用 `ubus` JSON-RPC 协议。

### 端点探测

```bash
# 检查 ubus 端点是否可用
curl -s -o /dev/null -w "%{http_code}" http://<IP>/ubus

# 如果返回 400（不是 404），说明 ubus 可用
```

### 枚举所有 RPC 对象

```bash
curl -s -X POST http://<IP>/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"list"}'
```

返回结果是已知固件所有 ubus 对象名称的数组。

### 识别关键 RPC 对象

| 对象名 | 出现固件 | 说明 |
|--------|---------|------|
| `session` | OpenWrt/LuCI 全系 | 会话管理、登录 |
| `system` | OpenWrt/LuCI 全系 | 系统信息 |
| `uci` | OpenWrt/LuCI 全系 | 配置读写 |
| `xapi.*` | **Newifi/PandoraBox stock** 特有 | 扩展 API |
| `xqapi.*` / `xqsystem` | **小米/Redmi stock** 特有 | 小米 API |
| `misystem` | **小米 stock** 特有 | 小米系统 API |
| `network` | OpenWrt/LuCI 全系 | 网络状态 |
| `network.interface.*` | OpenWrt 全系 | 接口状态 |
| `file` | OpenWrt | 文件读写 |
| `luci2.*` | Newifi/现代 LuCI | LuCI v2 方法 |

## 4. 匿名权限探测

### 用默认 session ID 调用

```bash
# 默认 session ID 通常是全部 0 的 32 位 hex 串
SID="00000000000000000000000000000000"

# 检查 session 自身权限
curl -s -X POST http://<IP>/ubus \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"$SID\",\"session\",\"access\",{\"scope\":\"ubus\",\"object\":\"session\",\"function\":\"access\"}]}"

# 检查各 scope 的通配权限
for scope in ubus uci file; do
  result=$(curl -s -X POST http://<IP>/ubus \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"call\",\"params\":[\"$SID\",\"session\",\"access\",{\"scope\":\"$scope\",\"object\":\"*\",\"function\":\"*\"}]}")
  echo "$scope → $(echo "$result" | grep -oP '"access":\K[^}]+')"
done
```

### 探测哪些对象方法可以匿名调用

```bash
# 基础信息查询（通常公开）
curl -s -X POST http://<IP>/ubus \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"$SID\",\"xapi.basic\",\"get_version\",{}]}"

curl -s -X POST http://<IP>/ubus \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"$SID\",\"system\",\"info\",{}]}"

# 返回格式分析和模式判断：{"result":[0, {...}]} = 成功；{"error":{...}} = 被拒
```

## 5. 初始化状态判定

### 方法 A：通过返回代码判断

| 匿名接口行为 | 可能状态 |
|-------------|---------|
| 敏感接口返回 `Access denied` | 已初始化（有密码） |
| 敏感接口返回非 0 错误码 | 可能未初始化（系统未就绪） |
| 敏感接口成功返回数据 | **未初始化**，无访问控制 |

### 方法 B：通过 Web 模板判断

```bash
# 检查常见模板文件是否存在
for t in status overview login init setup sysauth main; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://<IP>/newifi/template/${t}.htm")
  echo "$code /newifi/template/$t.htm"
done
```

| 模板存在模式 | 含义 |
|-------------|------|
| 只有 `sysauth.htm` | 已初始化（需登录） |
| `status.htm` + `overview.htm` + 其他模板存在 | 可能是 OpenWrt 或其他固件 |
| 无模板 | 非 Newifi 固件，或固件不同 |

### 方法 C：通过 session.login 错误码

```bash
# 尝试用默认密码登录
curl -s -X POST http://<IP>/ubus \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"call","params":["$SID","session","xapi_login",{"username":"admin","password":"admin"}]}'
```

| 错误码 | 含义 |
|--------|------|
| `result: [0, {sid: "..."}]` | 登录成功 |
| `result: [6]` | **密码错误**（ubus 标准：6=Permission denied） |
| `result: [2]` | 参数错误（username/password 字段名不对） |
| `error: {...}` | API 不存在（login 使用其他机制） |

## 6. 登录测试常见凭据

```bash
for pwd in "admin" "root" "password" "" "123456" "admin123"; do
  result=$(curl -s -X POST http://<IP>/ubus \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"call\",\"params\":[\"$SID\",\"session\",\"xapi_login\",{\"username\":\"admin\",\"password\":\"$pwd\"}]}")
  # 解析结果
done
```

## 7. 实战案例：Newifi D2 (PandoraBox 3.2.1.7437)

2026-06-13 在 `192.168.99.1` 上的发现过程：

| 检查点 | 发现 |
|--------|------|
| 首页 title | `Lecoo` → Newifi 系列 |
| JS 框架 | `ng-app='newwifi'` |
| ubus 端点 | `POST /ubus` 可用 |
| ubus list | `xapi.*` 对象群 → **确认是 Newifi/PandoraBox** |
| xapi.basic.get_version | `platform: newifi-d2l` → 确认型号 |
| session.access | ubus/session/access → true；其余 `(*,*,*)` → false |
| 模板 | 只有 `sysauth.htm` → **已初始化** |
| session.xapi_login | 全部返回 code 6 → 密码已设置且非默认 |
| SSH 22 | Connection refused → **未启用** |

**结论**：一台已初始化的 Newifi D2（新路由 3），密码未知，SSH 关闭。下一步需要物理 Reset。

## 8. 不同固件的 API 特征速查

| 固件类型 | ubus | API 特征 | 登录方式 |
|---------|------|---------|---------|
| **小米 stock** | 无 ubus | `/cgi-bin/luci/;stok=/api/misystem/` | nonce + SHA1(password + KEY) |
| **Newifi/PandoraBox** | ✅ ubus | `xapi.*` 对象群 | `session.xapi_login` username/password |
| **OpenWrt 主线** | ✅ ubus | `system`, `network`, `uci`, `session` | `session.login` username/password |
| **Padavan** | 无 | `/api/*` | Web form 或 HTTP Basic Auth |
| **Breed bootloader** | 无 | `GET /index.html`, `POST /upload.html` | 无认证（bootloader 层） |
