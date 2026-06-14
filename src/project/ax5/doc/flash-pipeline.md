# AX5 刷机完整流水线 (Flash Pipeline)

从工厂态到 LibWrt/OpenWrt 的**端到端**流程。

## 快速入口

```bash
# 先编辑 INI 配置（firmware 路径等）
$EDITOR all_official_2_openwrt.ini

# 自动编排——自动检测工厂态/已初始化/降级/免降级
python3 all_official_2_openwrt.py

# 指定密码（非工厂态默认 admin）
python3 all_official_2_openwrt.py --pwd 12345678

# 自定义 INI 路径 + 调试
python3 all_official_2_openwrt.py --config my.ini --debug
```

INI 配置文件格式：
```ini
[firmware]
ubi_file = files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi
downgrade_file = files/RA67_1.0.26.bin
```

对于人类操作者或需要按步骤调试的场景，以下为各阶段的详细说明。

## 总览

```
阶段 0: 检测 / ping              get_router_info.sh / ping
       ↓
阶段 1: 出厂初始化               1.official_init.py              inited: 0 → 1
       ↓
阶段 2: 拿 stok                  2.login_get_stok.py
       ↓
阶段 3: 降级到 1.0.26            3.downgrade.py                  1.1.x/1.2.x/1.3.x/1.4.x → 1.0.26, 重启, inited→0
       ↓
[等待重启 ~45-60s]
       ↓
阶段 1': 重跑初始化              1.official_init.py              1.0.26 下, inited: 0 → 1
       ↓
阶段 2': 重拿 stok               2.login_get_stok.py             1.0.26 下
       ↓
阶段 3': ssid 注入开 SSH         4.enable_ssh.py                 SSH 端口 22 ready
       ↓
阶段 4: 上传固件                 5.firmware_upload_on_miwifi.py  scp 到 /tmp/
       ↓
阶段 5: 烧镜像                   6.miwifi_2_openwrt.py           ubiformat 烧对侧 mtd
       ↓
阶段 6: 切启动分区               set_miwifi_uboot_partition.sh
       ↓
阶段 7: 重启                     miwifi_ssh --cmd reboot
       ↓
阶段 8: 应用 overlay (可选)      7.custom_openwrt.py
       ↓
[OpenWrt @ 192.168.1.1, root/admin]
```

**2026-06-14 实机验证**：RA67 1.2.10 → 降级 1.0.26 → LibWrt 25.12-SNAPSHOT 全链路通过。

**已验证可降级的 stock 版本范围**：1.1.x / 1.2.x / 1.3.x / 1.4.x（均需降级到 1.0.26 才能开 SSH）。

> 完整原理见各子文档：
> - [enable-ssh.md](enable-ssh.md) — 阶段 3' 漏洞机制
> - [model-info.md](model-info.md) — 阶段 4-5 硬件参数

## 设计原则

| 原则 | 体现 |
|------|------|
| **能问路由器就别写常量** | KEY/IV 从 `init.<hash>.js` 运行时扒；SSID 从 `init_info.routername` 拿；不在脚本里写死 |
| **零文件服务器** | SSH 开启全程 ssid 字段直接注入命令，不起 HTTP server（学"既然能注入 curl，为什么不注入脚本本身"）|
| **职责分离** | step 1 = init；step 3 = downgrade；step 4 = ssh；step 5-6 = flash；step 7 = overlay |
| **统一 JSON 接口** | 所有工具脚本 stdout 必含 `ok` / `ip`，失败时 `error` + `reason` |
| **SSH 复用** | 阶段 4-5 走 `miwifi_ssh.sh --cmd`，不在工具脚本里写 sshpass |
| **失败大声报** | 每一阶段退出码 + JSON `ok` 字段双重信号 |
| **不碰 U-Boot / MIBIB** | 学 AX6 直接 ubiformat 到非活跃 rootfs，由 `set_miwifi_uboot_partition.sh` 改 nvram flag 切启动 |

## 阶段 0: 恢复出厂（可选，已初始化跳过）

如果路由器已经在 `inited=1` 状态，**跳过**这步（密码已知直接走阶段 1+2）。

```bash
# 拿当前 stok（如果 inited=1）
STOK=$(python3 2.login_get_stok.py --pwd 12345678 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['stok'])")

# 触发恢复
./router_official_recovery.sh --stok "$STOK"

# 轮询 ~45-60s 等 init_info 返回 inited=0
while true; do
  I=$(curl -s -m 2 http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('inited',''))" 2>/dev/null)
  [ "$I" = "0" ] && break
  sleep 2
done
```

## 阶段 1: 出厂初始化

第一次跑（1.1.x/1.2.x/1.3.x/1.4.x 工厂态）：

```bash
python3 1.official_init.py --admin-pwd 12345678
# 输出: {"ok": true, "step": "official_init", "data": {"stok": "..."}}
```

**关键内部动作**：
- 扒 `init.<hash>.js` 拿 KEY/IV
- 计算密码 SHA1 摘要
- POST `/api/xqsystem/init` 触发 router 初始化（inited 0→1）
- POST `/api/xqsystem/set_router_normal` 提交 WAN 配置
- POST `/api/xqsystem/set_wifi` 设 WiFi 密码
- 关闭自动更新

## 阶段 2: 登录拿 stok

```bash
python3 2.login_get_stok.py --pwd 12345678
# 输出: {"ok": true, "data": {"stok": "..."}}
```

## 阶段 3: 降级到 1.0.26 ⚠️ AX5 独有

**1.1.x / 1.2.x / 1.3.x / 1.4.x 均屏蔽了 ssid 注入漏洞，必须先降级**。

```bash
# 1.0.26 文件
FW=files/RA67_1.0.26.bin

# 触发降级
python3 3.downgrade.py --stok <stok> --file "$FW"
```

也可以用 stdin 管道：
```bash
python3 2.login_get_stok.py --pwd 12345678 \
  | python3 3.downgrade.py --file "$FW" --debug
```

**降级内部动作**（2 步，**跳过** AX6 的 syslock + flash_permission）：
1. `POST /api/xqsystem/upload_rom` 多部分上传固件
2. `POST /api/xqsystem/flash_rom?custom=1&recovery=1` 触发刷写
3. 路由器**自动重启**

**降级后状态变化**：
- NVRAM 被清 → `inited=0`
- JS hash 变化（`init.7e38f194f721344afd11.js` → `init.69d3c3412093717fdb4b.js`）
- 需重跑阶段 1+2（下面 1' / 2'）

## [等待重启] ~60-90s

```bash
while true; do
  result=$(curl -s --connect-timeout 2 \
    "http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info" 2>/dev/null)
  echo "$result" | grep -q '"inited"' && break
  sleep 3
done
# 期望: {"romversion":"1.0.26", ..., "inited":0, ...}
```

## 阶段 1': 重跑初始化（1.0.26 下）

```bash
python3 1.official_init.py --admin-pwd 12345678
# 期望: {"ok": true, ..., "firmware_version": "1.0.26"}
```

## 阶段 2': 重拿 stok（1.0.26 下）

```bash
python3 2.login_get_stok.py --pwd 12345678
# 期望: {"ok": true, "data": {"stok": "..."}}
```

## 阶段 3': ssid 注入开 SSH

```bash
python3 2.login_get_stok.py --pwd 12345678 \
  | python3 4.enable_ssh.py --debug
# 期望: {"ok": true, "step": "enable_ssh", "data": {"ssh_port": 22, "root_password": "root"}}
```

**实测内部命令序列**（4 组共 12 条注入）：
- 2 短命令：nvram set ssh_en=1 + nvram commit
- 3 短命令：echo root + echo root + passwd root
- 5 短命令（分块写 /tmp/e）：sed dropbear 解除 release 检查
- 2 短命令：dropbear enable + restart
- 1 短命令：rm -f /tmp/e /tmp/x

详见 [enable-ssh.md](enable-ssh.md)。

## 阶段 4: 烧镜像 ⚠️

### 关键原则

- **"哪个 mtd 是哪个系统"不是固定的**——烧前**先**用 `check_boot_partition.sh` 探测当前活跃 mtd，新镜像烧到**不活跃**的 mtd（保留当前作回退）
- **烧和切是两步**——`6.miwifi_2_openwrt.py` **只烧**不切，切用 `set_miwifi_uboot_partition.sh`

| 当前活跃 | 新镜像写到 | 命令 |
|---------|-----------|------|
| `mtd18` (rootfs) | **mtd19** (rootfs_1) | `6.miwifi_2_openwrt.py --part 1` |
| `mtd19` (rootfs_1) | **mtd18** (rootfs) | `6.miwifi_2_openwrt.py --part 0`（默认自动选对侧）|

### 操作

```bash
# 1) 探测当前活跃 mtd（参考用，脚本内部也会自动探测）
./check_boot_partition.sh
# {"ok": true, "current_partition": "rootfs_1", "current_mtd": "mtd19", ...}

# 2) 上传 .ubi/.bin 到 /tmp/
./5.firmware_upload_on_miwifi.py --file files/libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi

# 3) 烧到对侧 mtd（自动探测+安全检查）
# ⚠️ --file-name 传 basename，不是完整路径！
python3 6.miwifi_2_openwrt.py --file-name libwrt-qualcommax-ipq60xx-redmi_ax5-squashfs-factory.ubi
```

**`6.miwifi_2_openwrt.py` 输出**（成功）：

```json
{
  "ok": true,
  "current_mtd": "mtd19",          ← 当前活跃
  "target_mtd": "mtd18",           ← 烧的目标（对侧）
  "writing_to_inactive": true,     ← 对侧烧，安全
  "next_step": "1) 可选切启动分区: ./set_miwifi_uboot_partition.sh --part 0\n2) reboot 激活"
}
```

## 阶段 5: 切启动分区

烧完后**单纯**设 3 个 env flag 让 uboot 下次从新 mtd 启动。

**`set_miwifi_uboot_partition.sh`** 封装了这个逻辑，**只**切 flag 不做别的：

| `--part` | `flag_try_sys1_failed` | `flag_try_sys2_failed` | `flag_boot_rootfs` | 下次启动 |
|----------|------------------------|------------------------|---------------------|----------|
| **0** | `0`（sys1 成功）| `1`（sys2 失败）| `0`（当前在 0）| **mtd18** (rootfs) |
| **1** | `1`（sys1 失败）| `0`（sys2 成功）| `1`（当前在 1）| **mtd19** (rootfs_1) |

**第一个 flag 是 bootmiwifi 真正读的**——后两个是 stock init 一致性用。

```bash
# 切到 mtd18（刚烧好的）
./set_miwifi_uboot_partition.sh --part 0
# {"ok": true, "ip": "...", "part": 0,
#  "flags": {"flag_try_sys1_failed": "0", "flag_try_sys2_failed": "1", "flag_boot_rootfs": "0"}}

# reboot
./miwifi_ssh.sh --cmd 'reboot'
```

## 阶段 6: 等待 + 验证

**最直观的信号是 IP 变化**——不同系统默认不同：

| 系统 | 默认 IP | SSH 主机密钥 | root 密码 |
|------|---------|--------------|-----------|
| 小米 stock | `192.168.31.1` | RSA | 无（用密钥或临时密码）|
| OpenWrt / LibWrt | `192.168.1.1` | ED25519 | `admin`（LibWrt 编译时设置）|

```bash
# 等 ~30-90s
for i in $(seq 1 40); do
  for ip in 192.168.1.1 192.168.31.1; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://$ip" 2>/dev/null)
    [ "$code" != "000" ] && { echo "$ip ready"; break 2; }
  done
  sleep 3
done

# SSH 进 LibWrt
sshpass -p admin ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@192.168.1.1 \
  'cat /etc/openwrt_release; uname -a; cat /proc/cmdline'
# 期望: DISTRIB_ID='LibWrt',  ubi.mtd=rootfs (即 mtd18)
```

## 阶段 7: 应用自定义 overlay（可选）

刷完 OpenWrt 后可以把本地 `.tar.gz` overlay 推到 `/overlay/upper/`，自动 reboot。

```bash
# tar.gz 解压后顶层必须是 overlay/ 目录
python3 7.custom_openwrt.py --file files/mocktool-overlay.tar.gz
# {"ok": true, "step": "custom_openwrt", "data": {..., "reboot": true}}
```

---

## 一键命令

### 全自动编排（推荐）

```bash
# 先编辑 INI → 直接跑
python3 all_official_2_openwrt.py

# 调试模式
python3 all_official_2_openwrt.py --debug
```

### 手动逐步执行（调试用）

```bash
cd src/project/ax5

# 0. 检测
./get_router_info.sh

# 1. 初始化（工厂态才需要）
python3 1.official_init.py --admin-pwd 12345678

# 2. 拿 stok
python3 2.login_get_stok.py --pwd 12345678

# 3. 降级（1.1.x/1.2.x/1.3.x/1.4.x 必须）
python3 3.downgrade.py --stok <stok> --file files/RA67_1.0.26.bin
# ↓ 等 ~45-60s 重启完成

# 4. 重初始化 + 开 SSH（1.0.26 下）
python3 1.official_init.py --admin-pwd 12345678
python3 2.login_get_stok.py --pwd 12345678
python3 4.enable_ssh.py --stok <stok>
# ↓ 等几秒 SSH 22 就绪

# 5. 上传 + 刷
python3 5.firmware_upload_on_miwifi.py --file files/libwrt-...-factory.ubi
python3 6.miwifi_2_openwrt.py --file-name libwrt-...-factory.ubi

# 6. 切分区 + 重启
./set_miwifi_uboot_partition.sh --part 0
./miwifi_ssh.sh --cmd reboot
```

实测运行时间：

| 阶段 | 耗时 |
|------|------|
| 阶段 1+2 (1.4.31 工厂态) | ~6s |
| 阶段 3 降级 | ~3s |
| 阶段 3.5 等待重启 | **~42s** |
| 阶段 1'+2' (1.0.26 重新初始化) | ~6s |
| 阶段 3' ssid 注入开 SSH | ~10s |
| 阶段 4-5 上传+烧+切分区 | ~10s |
| 阶段 6 reboot+等 OpenWrt | **~30s** |
| **总计（工厂态 → LibWrt 上线）** | **~2min** |

## 验证清单

跑完后 SSH 进 LibWrt 跑这 8 行确认一切就位：

```bash
sshpass -p admin ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@192.168.1.1 '
  echo "=== 1) OS ==="
  cat /etc/openwrt_release
  echo "=== 2) 内核 ==="
  uname -a
  echo "=== 3) cmdline ==="
  cat /proc/cmdline
  echo "=== 4) MTD ==="
  cat /proc/mtd | grep -E "rootfs|kernel"
  echo "=== 5) 网络 ==="
  ip addr | grep -E "inet |eth|br-"
  echo "=== 6) 启动 nvram flag (应全部空因为是 OpenWrt) ==="
  nvram get flag_boot_rootfs 2>&1
  echo "=== 7) dropbear 端口 ==="
  netstat -tlnp 2>/dev/null | grep :22
  echo "=== 8) overlay 挂载 ==="
  mount | grep overlay
'
```

期望：
1. `DISTRIB_ID='LibWrt'` 或 `OpenWrt`
2. 内核版本 ≥ 5.x
3. `ubi.mtd=rootfs` (即 mtd18)
4. mtd18=rootfs (36MB), mtd19=rootfs_1 (36MB)
5. LAN `192.168.1.1/24`, WAN DHCP
6. `nvram: not found` 或空（OpenWrt 不用 nvram）
7. `0.0.0.0:22` LISTEN
8. `overlayfs:/overlay on /`

## 关联文档

- [enable-ssh.md](enable-ssh.md) — 阶段 3' 漏洞机制详解
- [model-info.md](model-info.md) — 硬件参数、MTD 映射
- [troubleshooting.md](troubleshooting.md) — 各阶段 `reason` → 恢复方案
