# AX3600 刷机完整流水线 (Flash Pipeline)

## 快速入口

```bash
# 编辑 INI → 直接跑
$EDITOR all_official_2_openwrt.ini
python3 all_official_2_openwrt.py
python3 all_official_2_openwrt.py --debug
```

## 概述

从工厂态到能 SSH 进路由器 / 刷入 OpenWrt 的**端到端**流程。

⚠️ **关键**：AX3600 的 `set_config_iotdev` ssid 注入漏洞在 **1.1.x 已被封堵**。
1.1.x 工厂态必须先走步骤 4 降级到 1.0.17，再走步骤 1/2/3 开 SSH。

## 总览（1.0.17 工厂态 — 最简路径）

```
步骤 1: 1.official_init.py           ← 初始化设置密码
步骤 2: 2.login_get_stok.py          ← 拿 stok
步骤 3: 3.enable_ssh.py --wait       ← 注入开 SSH (root/root)
步骤 4: 4.official_upgrade.py        ← 可选, 刷 OpenWrt / 升回新版
```

## 总览（1.1.x 工厂态 — 降级迂回路径）

```
步骤 4: 4.official_upgrade.py        ← 先降级到 1.0.17 (清 NVRAM)
                                          ↓ ~45s 重启, 回到 inited=0
步骤 1: 1.official_init.py           ← 重新初始化
步骤 2: 2.login_get_stok.py          ← 拿新 stok
步骤 3: 3.enable_ssh.py --wait       ← 注入开 SSH
```

## 总览（1.1.x 工厂态 — 直接刷 OpenWrt, 跳过 SSH）

```
步骤 4: 4.official_upgrade.py        ← 直接刷 libwrt .ubi (custom=1)
```

## 实测时间表

| 阶段 | 1.0.17 实测 | 1.1.25 → 1.0.17 迂回实测 |
|------|-------------|--------------------------|
| 1.official_init | ~3s | ~3s |
| 2.login_get_stok | <1s | <1s |
| 3.enable_ssh | ~20s (等 SSH 端口) | ~20s |
| 4.official_upgrade (降级) | ~5s + ~45s 重启 | ~5s + ~45s 重启 |

> 1.0.17 全过实测 2026-06-09 `26677/E0P534252`（同一台机器，从 1.1.25 降级而来）

## 步骤详解

### 步骤 1：出厂初始化

参见 [`README.md`](README.md#步骤-1官方初始化1official_initpy) 和 [`init-login.md`](init-login.md)。

### 步骤 2：登录拿 stok

参见 [`README.md`](README.md#步骤-2登录获取-stok2login_get_stokpy) 和 [`init-login.md`](init-login.md)。

### 步骤 3：注入开 SSH

参见 [`enable-ssh-iotdev.md`](enable-ssh-iotdev.md)。

**4 步注入序列**：nvram 设置 → sed channel → root 密码 → dropbear restart
**所有 4 步通过单条 POST 链路完成**，无需时间操控 / scene 调度 / 任何辅助 WiFi。

### 步骤 4：刷固件

参见 [`upgrade.md`](upgrade.md)。

关键参数：
- `syslock?flashtype=upload&downgrade=1` —— 永远带，免版本检查
- `flash_rom?custom=1&recovery=1` —— custom 允许非官方固件，recovery 清 NVRAM

## 一键命令（1.0.17 工厂态）

**⚠️ 重要：`1.official_init.py` 返回的 stok 初始化完成后立即失效。**

原因：
- `1.official_init.py` 用**旧密码 admin** 登录拿到 stok
- 用 stok 调用 `set_router_normal` 把密码改成 `--admin-pwd`
- 密码一旦修改，**旧 stok 立即失效**（小米体系的安全机制）
- 必须**重新用新密码登录**拿新 stok

**正确流程**：

```bash
cd src/project/ax3600

# 步骤 1: 初始化（丢弃其返回的 stok，因改密后失效）
python3 1.official_init.py --admin-pwd 12345678

# 步骤 2: 用新密码重新登录，拿有效 stok
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 步骤 3: 用新 stok 开 SSH
python3 3.enable_ssh.py --stok "$STOK" --wait

ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1   # 密码: root
```

## 一键命令（1.1.x 工厂态，先降级）

**⚠️ 重要：`1.official_init.py` 返回的 stok 改密后立即失效。** 每次 init 后必须用 `2.login_get_stok.py` 重新拿 stok。

```bash
cd src/project/ax3600

# 步骤 1: 1.1.x 工厂态初始化
python3 1.official_init.py --admin-pwd 12345678
# ⚠️ 丢弃返回的 stok（改密后失效）

# 步骤 2: 用新密码重新登录，拿有效 stok
STOK=$(python3 2.login_get_stok.py --pwd 12345678 | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")
echo "step 1+2 OK, stok=$STOK"

# 步骤 3: 降级到 1.0.17（recovery=1 清 NVRAM，~45s 重启后回到 inited=0）
python3 4.official_upgrade.py --stok "$STOK" --file files/R3600_1.0.17.bin

# ⚠️ 注意：recovery=1 会清 NVRAM，路由器重启后回到 inited=0
# ⚠️ 但 STOK 是降级**前**拿的，路由器重启后该 stok 也可能失效
# 安全做法：降级后重新 init + login

sleep 60  # 等路由器重启完成

# 步骤 4: 重新初始化 (1.0.17 工厂态)
python3 1.official_init.py --admin-pwd 12345678
# ⚠️ 丢弃返回的 stok（改密后失效）

# 步骤 5: 用新密码重新登录，拿新有效 stok
NEW_STOK=$(python3 2.login_get_stok.py --pwd 12345678 | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")
echo "step 4+5 OK, new stok=$NEW_STOK"

# 步骤 6: 用新 stok 开 SSH
python3 3.enable_ssh.py --stok "$NEW_STOK" --wait

ssh -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1   # 密码: root
```

## 失败模式速查

| 现象 | 阶段 | 原因 | 解决 |
|------|------|------|------|
| `set_config_iotdev` 返 `code:1523` | 3 | 1.1.x 已封堵 | 先步骤 4 降级到 1.0.17 |
| `nonce 1582` | 1 | 首次 init 偶发 | 重试 2-3 次 |
| 登录 `code 401 not auth` | 1 | 路由器已初始化 | 跳过步骤 1；知道密码就直接 2.login_get_stok.py，不知道就按 Reset |
| flash 报 `code:1532` | 4 | 固件签名不对 | 用对型号的 `.bin` (R3600 不是 RA69) |

## 验证清单

刷完后 SSH 进去确认：

```bash
cat /proc/version                              # Linux 4.4.60 (stock)
nvram get ssh_en                               # 1
cat /etc/init.d/dropbear | grep channel        # channel="debug"
```

## 关联文档

- [README.md](README.md) — 主文档，步骤概览
- [init-login.md](init-login.md) — 步骤 1 密码学
- [enable-ssh-iotdev.md](enable-ssh-iotdev.md) — 步骤 3 set_config_iotdev 注入详解
- [upgrade.md](upgrade.md) — 步骤 4 4 步 API 链
- [recovery.md](recovery.md) — `router_official_recovery.sh` 恢复出厂