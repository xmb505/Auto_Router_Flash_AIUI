# AX5 故障排查 (Troubleshooting)

> AI 通过脚本输出 JSON 的 `reason` 字段查本表 → 恢复方案。
> **新发现的问题必须同步更新本文档**。

## 索引

| reason | 触发脚本 | 含义 | recoverable |
|--------|----------|------|-------------|
| `command_too_long` | 4.enable_ssh.py | 命令超 30 字节未分块 | false |
| `inject_failed` | 4.enable_ssh.py | ssid 注入 HTTP 错误 | true |
| `stok_expired` | 全部 Python | HTTP 401/403，stok 失效 | true |
| `ssh_failed` | 6.miwifi_2_openwrt.py | SSH 连接失败（dropbear 未启或算法不匹配）| true |
| `file_not_found` | 6.miwifi_2_openwrt.py | 远端 /tmp/ 下找不到文件 | true |
| `mtd_write_failed` | 6.miwifi_2_openwrt.py | ubiformat 失败 | true |
| `flash_refused` | 3.downgrade.py | 路由器拒绝降级（版本检查）| false |
| `init_nonce_1582` | 1.official_init.py | init 偶发 nonce 错误 | true |
| `hostkey_negotiation` | miwifi_ssh.sh | 缺少 ssh-rsa 算法选项 | true |
| `inited_mismatch` | 2.login_get_stok.py | inited≠1 但尝试登录 | true |

## 详细恢复方案

### `command_too_long`

**触发**：单条命令字节数 > `MAX_SSID_CMD_LEN` (30) 走了 `exec_short_cmd` 路径

**恢复**：
1. 该命令应走 `exec_long_cmd()` 路径（自动分块写 /tmp/e）
2. 检查脚本调用方是否误用了 short 路径
3. 当前 `4.enable_ssh.py` 内部对 sed 那个 49 字节命令已用 long 路径

### `inject_failed`

**触发**：`set_config_iotdev` 返回非 0 code（如 `code != 0`）

**原因**：
- stok 失效（init 改了密码、stock 重启）
- 1.1.x/1.2.x/1.3.x/1.4.x 修复了 ssid 注入漏洞（**必须先降级**）

**恢复**：
```bash
# 1. 拿新 stok
python3 2.login_get_stok.py --pwd 12345678

# 2. 如果是 1.1.x+：先降级
python3 2.login_get_stok.py --pwd 12345678 \
  | python3 3.downgrade.py --file files/RA67_1.0.26.bin
# 等重启 → 重跑 init+login → 再试 4.enable_ssh.py
```

### `stok_expired`

**触发**：HTTP 响应包含 `code: 401` 或 `code: 403`

**原因**：
- 路由器重启（stok 绑 session）
- 长时间空闲（stok TTL）
- 路由器密码变了

**恢复**：
```bash
python3 2.login_get_stok.py --pwd <当前密码>
# 然后用新 stok 重跑失败的步骤
```

### `ssh_failed`

**触发**：`miwifi_ssh.sh` 连接失败或返回 `ok: false`

**原因**：
- dropbear 没起（阶段 3' 没成功）
- 主机密钥算法不匹配（新 OpenSSH 拒绝老 RSA）
- 路由器离线

**恢复**：
```bash
# 1) 测端口
bash -c "echo > /dev/tcp/192.168.31.1/22" 2>&1

# 2) 看 miwifi_ssh.sh 是否带 ssh-rsa 选项
grep -n "HostKeyAlgorithms" miwifi_ssh.sh
# 必须有 -oHostKeyAlgorithms=+ssh-rsa（老 dropbear only 支持 RSA）

# 3) SSH 验证
sshpass -p root ssh -oHostKeyAlgorithms=+ssh-rsa -oStrictHostKeyChecking=no \
  -oUserKnownHostsFile=/dev/null root@192.168.31.1 'uname -a'
```

### `file_not_found`

**触发**：`ls -la /tmp/<file>` 找不到文件

**原因**：
- **常见**：`--file-name` 传了完整路径（`files/xxx.ubi`）而不是 basename
- 5.firmware_upload_on_miwifi.py 没跑 / 失败
- 上传到一半网络中断

**恢复**：
```bash
# ⚠️ --file-name 传 basename，不是完整路径
python3 6.miwifi_2_openwrt.py --file-name libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi

# 验证 /tmp/ 下确有文件
./miwifi_ssh.sh --cmd 'ls -la /tmp/'

# 重传
./5.firmware_upload_on_miwifi.py --file files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi
```

### `mtd_write_failed`

**触发**：`ubiformat` exit code != 0

**原因**：
- 目标 mtd 写保护
- 文件大小 > mtd 大小（36MB）
- mtd 设备忙

**恢复**：
```bash
# 1) 手动 SSH 跑 ubiformat 看完整错误
./miwifi_ssh.sh --cmd 'ubiformat /dev/mtd18 -q -y -f /tmp/libwrt-xxx.ubi 2>&1'

# 2) 看 mtd 大小和文件大小
./miwifi_ssh.sh --cmd 'cat /proc/mtd | grep rootfs; ls -la /tmp/libwrt-xxx.ubi'

# 3) 验 mtd 是否干净
./miwifi_ssh.sh --cmd 'ubiformat /dev/mtd18 -q -y 2>&1 | head -20'  # 不指定文件，看 attach 状态
```

### `flash_refused`

**触发**：`flash_rom` 返回错误（不重启）

**原因**：
- 1.4.31 强制阻止降级到 1.0.26（"新固件必须 ≥ 当前"）
- 上传后 token 校验失败
- 固件签名不匹配

**恢复**：
```bash
# 1) 看路由器 syslog
./miwifi_ssh.sh --cmd 'dmesg | tail -20'
./miwifi_ssh.sh --cmd 'logread | tail -20'

# 2) 看 flash_rom 完整响应
python3 2.login_get_stok.py --pwd 12345678 | python3 -c "
import sys, json
stok = json.load(sys.stdin)['data']['stok']
import urllib.request
url = f'http://192.168.31.1/cgi-bin/luci/;stok={stok}/api/xqsystem/flash_rom?custom=1&recovery=1'
r = urllib.request.urlopen(url, data=b'').read()
print(r.decode())
"
```

### `init_nonce_1582`

**触发**：`set_router_normal` 返回 `code: 1582`，error 含 `nonce`

**原因**：小米前端对 `set_router_normal` 有 anti-replay nonce，多次快速 POST 会撞

**恢复**：
```bash
# 简单方案：重试 1-2 次
python3 1.official_init.py --admin-pwd 12345678
if [ $? -ne 0 ]; then
  sleep 2
  python3 1.official_init.py --admin-pwd 12345678
fi
```

### `hostkey_negotiation`

**触发**：`no matching host key type found. Their offer: ssh-rsa`

**原因**：本机 OpenSSH ≥ 8.8 默认禁用 ssh-rsa，老 dropbear 只支持 ssh-rsa

**恢复**：
```bash
# 一次性：命令行加 -oHostKeyAlgorithms=+ssh-rsa
sshpass -p root ssh -oHostKeyAlgorithms=+ssh-rsa -oStrictHostKeyChecking=no \
  -oUserKnownHostsFile=/dev/null root@192.168.31.1 'uname -a'

# 永久：写到 ~/.ssh/config
cat >> ~/.ssh/config <<EOF
Host 192.168.31.1
  HostKeyAlgorithms +ssh-rsa
  PubkeyAcceptedAlgorithms +ssh-rsa
EOF
```

`miwifi_ssh.sh` 已内置 `HostKeyAlgorithms=+ssh-rsa`，**用 `miwifi_ssh.sh` 不要直接 ssh**。

### `inited_mismatch`

**触发**：尝试登录时 `init_info.inited != 1`

**原因**：路由器被恢复出厂或刚降级

**恢复**：
```bash
# 重跑初始化（仅在 inited=0 时）
python3 1.official_init.py --admin-pwd 12345678
```

## 关键原则

1. **所有 reason 字段必须出现在本表**——新加 reason 必补条目
2. **优先查 reason 字段**，再回退到 `error` 文本
3. **recoverable=true 表示用户/AI 自动恢复**；`false` 需人工介入（如拆 flash）
4. **JSON 输出是唯一契约**——脚本 stderr 是给 debug 用的，AI 决策只看 stdout

## 关联文档

- [flash-pipeline.md](flash-pipeline.md) — 各阶段位置
- [enable-ssh.md](enable-ssh.md) — 4.enable_ssh.py 失败细节
- [model-info.md](model-info.md) — MTD/分区事实表
