# AX6 刷机完整流水线 (Flash Pipeline)

从工厂态到能 SSH 进路由器的**端到端**流程，**实测**过的命令序列。

## 总览

```
阶段 0: 恢复出厂        router_official_recovery.sh          （可选，已初始化跳过）
阶段 1: 出厂初始化       1.official_init.py                  inited: 0 → 1
阶段 2: 拿 stok        2.login_get_stok.py                inited=1, 拿登录令牌
阶段 3: 启用 SSH       3.enable_ssh.py                    SSH 端口 22 ready
阶段 4: 设 nvram flags  set_uboot_env.sh                  8 个 key 全 set
阶段 5: 烧镜像         5.firmware_upload → 6.烧           上传 + ubiformat
阶段 6: 切启动分区     set_miwifi_uboot_partition.sh      只 SSH 设 3 个 flag
阶段 7: 应用 overlay   7.custom_openwrt.py                scp → 解压到 /overlay/upper → reboot
```

每步用 ax6/ 下的工具脚本跑，工具脚本之间通过标准 JSON 接口 + 共享 SSH（`miwifi_ssh.sh`）通信。

> 完整原理见各子文档：
> - `recovery.md` — 阶段 0
> - `init-login.md` — 阶段 1 的密码学/字段语义
> - `enable-ssh-smartcontroller.md` — 阶段 3 的漏洞机制
> - `custom-openwrt.md` — 阶段 7 自定义 overlay
> - `04-utility-contract.md`（doc/conventions/）— 工具脚本接口约定

## 设计原则

| 原则 | 体现 |
|------|------|
| **能问路由器就别写常量** | KEY/IV 从 `init.<hash>.js` 运行时扒；SSID 从 `init_info.routername` 拿；不动 stat 不在脚本里写死 |
| **职责分离** | step 1 = init；step 3 = enable_ssh；不交叉 |
| **统一 JSON 接口** | 所有工具脚本 stdout 必含 `ok` / `ip`，失败时 `error` |
| **SSH 复用** | 阶段 2-4 走 `miwifi_ssh.sh --cmd`，不在工具脚本里写 sshpass |
| **失败大声报** | 每一阶段退出码 + JSON `ok` 字段双重信号 |

## 阶段 0: 恢复出厂（可选）

如果路由器已经在 `inited=1` 状态，**跳过**这步。否则：

```bash
# 先拿当前 stok
STOK=$(python3 2.login_get_stok.py --pwd 12345678 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 触发恢复
./router_official_recovery.sh --stok "$STOK"

# 轮询 ~45-60s 等 init_info 返回 inited=0
while [ -z "$(curl -s -m 2 http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("inited",""))' 2>/dev/null)" ]; do
  sleep 3
done
```

**注意**：recovery **清 NVRAM**（`ssh_en` 回到 `0`），所以 init 之后**必须**跑阶段 3 enable_ssh。

## 阶段 1: 出厂初始化

```bash
python3 1.official_init.py --admin-pwd 12345678
```

- 只在工厂态跑（`inited=0`）；已初始化会返回 `code 401 not auth`（保护机制）
- 4 步流程：扒 JS 拿 KEY/IV → login → set_wan → vas_switch → set_router_normal
- 1.1.x 自动加 `bw160=false`；1.0.x 不加
- 改 admin 密码为 `12345678`
- 完成后 `inited=1`

## 阶段 2: 拿 stok

```bash
python3 2.login_get_stok.py --pwd 12345678
```

- **已初始化**状态下登录（`init=0` 而非 `init=1`）
- 跟阶段 1 的区别见 init-login.md
- 输出 `{ok, stok, encrypt_mode, key_source}`
- 拿到的 stok 给阶段 3 用

## 阶段 3: 启用 SSH ⚠️ 关键

```bash
python3 3.enable_ssh.py --stok "$STOK"
```

- 利用 smartcontroller 漏洞（CVE-2023-26319）
- **无物理外设**——不需要辅助路由器（跟旧方案对比）
- 通过 HTTP API 注入系统命令
- 跑完 SSH 端口 22 ready，root 密码固定 `root`
- 完整漏洞机制见 `enable-ssh-smartcontroller.md`

**为什么必须这一步**：
- recovery 清空 NVRAM → `ssh_en=0`
- 阶段 1 `init` **不**开 SSH（step 1 / step 3 职责分离）
- 不跑这步，阶段 4 设 nvram 走不通（SSH 拒接）

**关键坑**：
- dropbear 的 `release` 检查：内置 `sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear`（**不能跳**）
- 跑完约 30-40 秒 SSH 端口才起
- 当前验证过的固件：1.0.16、1.1.3、1.1.10、1.1.17

## 阶段 4: 设置 nvram flags

```bash
./set_uboot_env.sh
```

8 个 key（按老版本刷机流程推荐）：

| Key | 值 | 作用 |
|-----|-----|------|
| `flag_last_success` | `0` | uboot 启动标志：上次成功 |
| `flag_boot_success` | `1` | 启动成功标志 |
| `flag_try_sys1_failed` | `0` | 系统 1 启动失败计数 |
| `flag_try_sys2_failed` | `0` | 系统 2 启动失败计数 |
| `boot_wait` | `on` | uboot 启动时等 tftp（断电刷固件用）|
| `uart_en` | `1` | UART 调试口开 |
| `telnet_en` | `1` | telnet 服务开 |
| `ssh_en` | `1` | SSH 服务开 |

**自定义 mode**（不跑默认 8 个）：

```bash
# 切下次启动到备胎
./set_uboot_env.sh --set flag_boot_rootfs=1

# 多个自定义 key
./set_uboot_env.sh --set flag_boot_rootfs=0 --set boot_wait=on
```

**`set` vs `verified` 字段**：

```json
{
  "ok": true,
  "mode": "default",
  "ip": "192.168.31.1",
  "set":      {"flag_last_success": "0", ...},   // 你**意图**设的值
  "verified": {"flag_last_success": "0", ...}    // commit 后 nvram get 实际存的
}
```

逐 key 比对 `set` vs `verified` → "我设的"和"存的"是否一致。如果 `verified` 是空字符串就是 commit 失败。

## 阶段 5: 烧镜像到指定 mtd ⚠️

上传 .ubi/.bin 到 `/tmp/`，然后 ubiformat 到指定 mtd。

### ⚠️ 关键原则

- **"哪个 mtd 是哪个系统"不是固定的**——烧前**先**用 `check_boot_partition.sh` 探测当前活跃 mtd，新镜像烧到**不活跃**的 mtd（保留当前作回退）
- **烧和切是两步**——`6.miwifi_2_openwrt.py` **只烧**不切，切用 `set_miwifi_uboot_partition.sh`

| 当前活跃 | 新镜像写到 | 工具 | 
|---------|-----------|------|
| `current_mtd: "mtd12"` | **mtd13** | `6.miwifi_2_openwrt.py --part 1` |
| `current_mtd: "mtd13"` | **mtd12** | `6.miwifi_2_openwrt.py --part 0` |

### 操作步骤

```bash
# 1) 探测当前活跃 mtd（参考用，脚本内部也会自动探测）
./check_boot_partition.sh

# 2) 上传 .ubi/.bin 到 /tmp/
./5.firmware_upload_on_miwifi.sh --file files/immortalwrt-25.12.0-xxx.ubi

# 3) 烧到指定 mtd（6 自动探测当前 mtd 做安全检查）
python3 6.miwifi_2_openwrt.py --file-name immortalwrt-25.12.0-xxx.ubi --part 1
#    --probe-only 先 dry-run 确认对侧
#    --yes 跳过"覆盖当前"警告
```

**`6.miwifi_2_openwrt.py` 输出**（成功）：

```json
{
  "ok": true,
  "current_mtd": "mtd12",          ← 当前活跃（参考）
  "target_mtd": "mtd13",           ← 烧的目标
  "writing_to_inactive": true,     ← 对侧烧，安全
  "ubiformat_output_excerpt": "...",
  "next_step": "切启动分区 + reboot"
}
```

## 阶段 6: 切启动分区

烧完后**单纯**设 3 个 env flag 让 uboot 下次从新 mtd 启动。

**`set_miwifi_uboot_partition.sh`** 封装了这个逻辑，**只**切 flag 不做别的：

| `--part` | `flag_try_sys1_failed` | `flag_try_sys2_failed` | `flag_boot_rootfs` | 下次启动 |
|----------|------------------------|------------------------|---------------------|----------|
| **0** | `0`（sys1 成功）| `1`（sys2 失败）| `0`（当前在 0）| mtd12 |
| **1** | `1`（sys1 失败）| `0`（sys2 成功）| `1`（当前在 1）| mtd13 |

**第一个 flag 是 bootmiwifi 真正读的**——后两个是 stock init 一致性用。

### 操作

```bash
# 切到 mtd13（刚烧好的）
./set_miwifi_uboot_partition.sh --part 1

# 或切回 mtd12
./set_miwifi_uboot_partition.sh --part 0
```

**输出**：
```json
{"ok": true, "ip": "192.168.31.1", "part": 1,
 "flags": {"flag_try_sys1_failed": "1", "flag_try_sys2_failed": "0", "flag_boot_rootfs": "1"},
 "next_step": "reboot 激活"}
```

### 验证切根成功

```bash
# reboot
./miwifi_ssh.sh --cmd 'reboot'
# 等 ~30-60s

# 用 check_boot_partition 确认
./check_boot_partition.sh
# {
#   "current_partition": "rootfs_1",  ← 新 mtd
#   "current_mtd": "mtd13",
#   "consistency": true
# }
```

**最直观的信号是 IP 变化**——不同系统默认不同：

| 系统 | 默认 IP | SSH key |
|------|---------|---------|
| 小米 stock | `192.168.31.1` | RSA |
| OpenWrt / ImmortalWrt | `192.168.1.1` | ED25519 |

---

## 阶段 7: 应用自定义 overlay（可选，刷完 OpenWrt 后用）

阶段 6 reboot 后路由器已经在 ImmortalWrt 上跑起来（`192.168.1.1`）。
这一步把一个本地 `.tar.gz` overlay 包推上去，写入 `/overlay/upper/`，自动 reboot。

**`7.custom_openwrt.py`** 干这一件事：**不复用**小米的 `miwifi_ssh.sh`，
走原生 `sshpass + scp/ssh`，因为 OpenWrt host key 是 ED25519、root 免密。

### 操作

```bash
# 上传 overlay + 写入 /overlay/upper + reboot
python3 7.custom_openwrt.py --file files/overlay-new.tar.gz

# 调试
python3 7.custom_openwrt.py --file files/overlay-new.tar.gz --debug
```

**包结构要求**：tar.gz 解压后顶层必须是 `overlay/` 目录，脚本执行
`cp -a overlay/* /overlay/upper/`。

打包示例：
```bash
tar -czf overlay-new.tar.gz -C /path/to/files overlay
```

### 输出

```json
{"ok": true, "step": "custom_openwrt", "data": {
  "ip": "192.168.1.1",
  "file": "files/overlay-new.tar.gz",
  "remote_path": "/tmp/overlay-new.tar.gz",
  "extract_marker": "OK",
  "reboot": true
}}
```

### 验证

```bash
# 等 reboot 完成（~45s）
ssh root@192.168.1.1 "ls /overlay/upper/"
# 看到 overlay 包里的文件树就 OK
```

详见 [`custom-openwrt.md`](custom-openwrt.md)。

切根后约 SSH host key 警告（`ssh-keygen -R <新 IP>` 清理旧条目）。

### ⚠️ mtd1 panic 现象

如果**老** mtd12 **已坏**——boot 时先加载 mtd1 小米 4.14 kernel → 挂 mtd12 panic → 回退 mtd13 OpenWrt。浪费 ~30s 但最终能进 OpenWrt。要消除：刷一份**好的** mtd12（原厂或 OpenWrt 双系统）。

---

## 验证

跑完所有阶段后，SSH 直查 8 个 key 确认：

```bash
./miwifi_ssh.sh --cmd 'for k in flag_last_success flag_boot_success flag_try_sys1_failed flag_try_sys2_failed boot_wait uart_en telnet_en ssh_en; do printf "%-25s = %s\n" "$k" "$(nvram get $k)"; done' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['stdout'])"
```

期望：8 行输出，每个值跟 `set_uboot_env.sh` 的 `verified` 字段字面相同。

## 一键命令（复制粘贴）

```bash
cd src/project/ax6

# ========== 阶段 0-4: 工厂态 → SSH 通 + nvram 设好 ==========

# 阶段 0: recovery（可选，已初始化跳过）
STOK=$(python3 2.login_get_stok.py --pwd 12345678 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")
./router_official_recovery.sh --stok "$STOK"
# 轮询 ~45-60s

# 阶段 1: init（nonce 1582 多试几次）
python3 1.official_init.py --admin-pwd 12345678
if [ $? -ne 0 ] && [ $? -ne 0 ]; then python3 1.official_init.py --admin-pwd 12345678; fi

# 阶段 2: 拿新 stok
STOK=$(python3 2.login_get_stok.py --pwd 12345678 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 阶段 3: enable_ssh
python3 3.enable_ssh.py --stok "$STOK"
# 轮询 ~30s SSH 端口 22 ready

# 阶段 4: set_uboot_env（8 个 flags）
./set_uboot_env.sh

# ========== 阶段 5-6: 烧镜像 + 切分区（可选，刷 OpenWrt 用）==========

# 阶段 5: 上传 .ubi + ubiformat 到对侧 mtd
./5.firmware_upload_on_miwifi.sh --file files/immortalwrt-25.12.0-xxx.ubi
python3 6.miwifi_2_openwrt.py --file-name immortalwrt-25.12.0-xxx.ubi --part 1

# 阶段 6: 切启动分区
./set_miwifi_uboot_partition.sh --part 1
./miwifi_ssh.sh --cmd 'reboot'
```

## 常见失败模式

| 失败点 | 表现 | 原因 | 修法 |
|--------|------|------|------|
| 阶段 0 轮询超时 | init_info 永远拿不到 | 路由器没在 192.168.31.1 网段 | 检查网线/电脑 IP |
| 阶段 1 `set_router_normal` 报 `nonce 1582` | init 失败，error 含 `workmode: 0, code: 1582` | 路由器的 nonce 历史被前 3 步污染，首次连接偶发 | **重试 2-3 次**；串联脚本必须内置重试（等待 1-2s 再试）|
| 阶段 1 报 `code 401 not auth` | init 失败 | 路由器**已经**初始化 | 跳过阶段 1，或先 recovery |
| 阶段 2 报 `登录失败` | 拿不到 stok | 密码不对 | 用 `2.login_get_stok.py --pwd admin` 试出厂默认 |
| 阶段 3 跑完 SSH 拒接 | port 22 closed | dropbear 没起来 | 看 `3.enable_ssh.py --debug` 的 sed 步骤 |
| 阶段 4 报 `无法连接路由器` | set_uboot_env 失败 | **SSH 没开** | 必须先跑阶段 3 enable_ssh |
| 阶段 4 verified 是空 | commit 失败 | 远端 nvram commit 错误 | 加 `--debug` 看真实 stderr |

## 实测时间表（1.0.16, 2026-06-09）

| 阶段 | 耗时 |
|------|------|
| recovery exit → 重启 → 上线 | **56s**（memory 估算 45s，实测 56s）|
| 1.official_init.py | ~3s |
| 2.login_get_stok.py | ~1s |
| 3.enable_ssh.py（含 32s 时间等待）| ~35s |
| set_uboot_env.sh | ~1s |
| **总计（从工厂态到 SSH 通 + nvram 设好）** | **~1.5-2min** |

## 当前验证过的固件

| 固件 | 覆盖阶段 | 数据来源 |
|------|---------|---------|
| 1.0.16 | ✅ **阶段 0-6** 全过 | 2026-06-09 实测 |
| 1.1.3 | ✅ 阶段 0-4 | 历史 |
| 1.1.10 | ✅ 阶段 0-4 | 历史 |
| 1.1.17 | ✅ 阶段 0-4 | 历史 |

> **未实测的固件（1.1.20+、2.x.x、跨大版本）**—— 别预设兼容性。脚本每次 init 都会运行时扒当前固件的 `init.<hash>.js` 拿最新 KEY/IV——新固件出现时按"先跑 `1.official_init.py` 看结果"流程处理；失败再 debug。
> 也不在文档/代码里"固化"任何 KEY/IV 值——避免被误读为"写死常量"。

## 关联文档

- [recovery.md](recovery.md) — 阶段 0 恢复出厂
- [init-login.md](init-login.md) — 阶段 1 密码学/字段语义
- [enable-ssh-smartcontroller.md](enable-ssh-smartcontroller.md) — 阶段 3 漏洞机制
- [upgrade.md](upgrade.md) — 阶段 3 之后用 `4.official_upgrade.py` 刷固件（双向，always pass `downgrade=1` + `recovery=1`）
- [custom-openwrt.md](custom-openwrt.md) — 阶段 7 应用自定义 overlay
- [switch-to-stock.md](switch-to-stock.md) — `switch_to_stock.sh` 反向操作（OpenWrt → 小米 stock）
- [../conventions/04-utility-contract.md](../../conventions/04-utility-contract.md) — 工具脚本 JSON 接口约定
