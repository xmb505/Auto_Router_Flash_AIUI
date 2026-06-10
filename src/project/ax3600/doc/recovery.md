# AX6 Recovery：官方系统重置

`router_official_recovery.sh` — 通过小米固件自带官方 API 一键重置配置。

## 用法

```bash
# 先拿 stok
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 恢复出厂（静默执行，成功无输出）
./router_official_recovery.sh --stok "$STOK"

# 想看过程加 --debug
./router_official_recovery.sh --stok "$STOK" --debug
```

## 重置后路由器发生了什么

复位命令返回 `exit 0` 后路由器**立即断电式重启**。

```
复位命令 exit 0
  ↓
路由器重启 ······ 约 45 秒 ······
  ↓
HTTP 服务重新上线 → init_info 返回 inited=0
```

重启期间路由器完全不可达——`curl` 超时或"连接拒绝"。  
**不存在** "NOT_READY" 之类状态码，路由器不会吐任何内容。

### 出厂默认值

| 属性 | 重置后 |
|------|--------|
| 管理密码 | `admin` |
| Wi-Fi SSID | `routername`（MAC 派生，如 `Redmi_E0B9_1F46`）|
| Wi-Fi 密码 | 无 |
| 小米账号绑定 | 解除（`bound=0`）|
| 固件版本 | 不变（reset 不清固件区）|
| `inited` | `0`（出厂态）|

### 上线后的 init_info

```json
{"inited":0, "romversion":"1.1.10", "routername":"Redmi_E0B9_1F46", ...}
```

## 轮询上线

重启后可用 `get_router_info.sh` 或直接 curl 确认上线：

```bash
while ! curl -s -m 3 http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info >/dev/null 2>&1; do
  sleep 5
done
echo "已上线"
```

## 完整闭环

```
2.login_get_stok.py → router_official_recovery.sh → 重启 → 出厂态
                                                     ↓
                                           1.official_init.py（可选，重新初始化）
```

## 技术细节

| 项 | 值 |
|----|-----|
| endpoint | `GET /cgi-bin/luci/;stok=<stok>/api/xqsystem/reset?format=0` |
| 成功响应 | `{"code":0}`（HTTP 200） |
| `format=0` | 清 NVRAM 配置，保留 user_data 分区 |
| `format=1` | 连 user_data 一起格式化（未实测） |
| exit 0 | 成功（默认无输出） |
| exit 1 | 路由器拒绝 / HTTP 错误 |
| exit 2 | 参数错误 |
| exit 3 | 网络错（无法连接） |
