# CR660X (CR6606 / CR6608 / CR6609) — 机型信息

**注意**：CR660X 是小米/红米路由器系列，**不**是单机型。实际硬件/固件以 `init_info` 的 `model` / `hardware` 字段为准。

## 已实测机型

| model (init_info) | 硬件 | 运营商 | 实测 |
|------|------|--------|------|
| `xiaomi.router.cr6606` | CR6606 | 中国联通 | ✅ 2026-06-11 |
| `xiaomi.router.cr6608` | CR6608 | 中国移动/电信 | 未实测 |
| `xiaomi.router.cr6609` | CR6609 | 中国移动/电信 | 未实测 |

## bootloader

**stock 固件**（未刷 pb-boot/breed）。

- HTTP 服务: `nginx/1.12.2`（CR6606 1.0.117 stock 自带，**不是** pb-boot 特征）
- API 兼容小米体系: `/cgi-bin/luci/api/xqsystem/init_info` 返回标准 init_info
- 工厂态 (inited=0): `GET /cgi-bin/luci/api/xqsystem/login?init=1&privacy=1&...`，密码 `admin`
- 已初始化: 同样接口，密码=用户设定的 admin 密码

## 实测硬件（CR6606 联通版）

| 项目 | 值 |
|------|-----|
| init_info romversion | `1.0.117` |
| model | `xiaomi.router.cr6606` |
| hardware | `CR6606` |
| **SoC** | **MediaTek MT7621A**（MIPS 1004Kc，双核 880MHz） |
| routername | `Xiaomi_8729_78D6`（MAC 派生） |
| id | `30298/J1RN25506` |
| inited | `0`（工厂态） |
| kernel | `4.4.198 #0 SMP Mon May 30 15:25:16 2022 mips` |
| OpenWrt base | `18.06-SNAPSHOT` (XiaoQiang) |
| arch | `mipsel_24kc` |
| banner | "Welcome to XiaoQiang!" |
| SSH 验证 | ✅ `ssh root@192.168.31.1` 密码 `root` 真进 root shell |
| modules | `replacement_assistant=1` |

## ⚠️ SoC 区别于 ax6/ax3600（重要）

| 维度 | CR660X | ax6/ax3600 |
|------|--------|------------|
| SoC | **MediaTek MT7621A** | Qualcomm IPQ8071A |
| 架构 | **MIPS 1004Kc**（mipsel） | ARMv8 Cortex-A53（aarch64） |
| OpenWrt target | `ramips/mt7621` | `ipq807x` |
| OpenWrt arch | `mipsel_24kc` | `aarch64_cortex-a53` |
| 工具链 | mipsel-openwrt-linux-musl-* | aarch64-openwrt-linux-musl-* |
| 主导 uboot | pb-boot / breed | breed / u-boot |

**绝对不要**给 CR 项目用 ax6/ax3600 的 ARM 工具链/库。移植时**先确认 SoC**，再决定工具。

## 密码学共享

跟所有小米路由器共享：

| 常量 | 值 |
|------|-----|
| `KEY` | `a2ffa5c9be07488bbb04a3a47d3c5f6a` |
| `IV` | `64175472480004614961023454661220` |
| 出厂密码 | `admin` |

**KEY/IV 运行时扒**：`/init.html` → 引用的 `init.<hash>.js` → regex `key:"..."` / `iv:"..."`。

## 默认网络

| 项目 | 值 |
|------|-----|
| 默认 IP (联通) | `192.168.1.1` |
| 默认 IP (移动/电信) | `192.168.31.1` 或 `192.168.2.1` |
| 默认密码 (工厂态) | `admin` |

## 步骤脚本

| # | 脚本 | 功能 | 状态 |
|---|------|------|------|
| 0 | `get_router_info.sh` | 探测 init_info（无鉴权） | ✅ 实测 |
| 1 | `1.official_init.py` | 工厂态初始化向导 | ✅ 实测 |
| 2 | `2.login_get_stok.py` | 已初始化后登录拿 stok | ✅ 实测 |
| 3 | `3.enable_ssh.py` | smartcontroller 漏洞启用 SSH | ✅ 实测 (真 SSH 进 root) |
| 4 | `4.firmware_upload_on_miwifi.sh` | scp 上传文件到路由器 /tmp | ✅ 实测 |
| - | `router_official_recovery.sh` | 恢复出厂 | ✅ 实测 |
| - | `miwifi_ssh.sh` | 一键 SSH 进路由器（交互/命令两种模式，JSON 数组输出） | ✅ 实测 |

## ⚠️ 重要设计决策：CR 系列不做双系统

**项目明确决策**（2026-06-11）：CR 系列路由器**不**做双系统（A/B partition）切换，**只**做破坏性刷机。

**与 mtd 布局无关**——用户 2026-06-11 明确："不要写mtd6, 我不关心那些，我只关心mtd0刷uboot"。所以本节**不**列具体 mtd 编号，只说设计意图。

设计意图：
- ❌ **不**写任何切双系统分区的脚本
- ❌ **不**写回退 stock 的脚本
- ❌ **不**维护 `flag_try_sys*_failed` / `flag_boot_rootfs` 互补 flag 逻辑
- ✅ 走破坏性刷机路线：固件烧 sysupgrade 一次性写完，刷错就重刷
- ⚠️ **不可逆**：刷 OpenWrt 后**没有**回退 stock 的捷径，只能编程器/裸 flash

**跟 ax6/ax3600 项目的设计取舍对比鲜明**：
- ax6/ax3600：保守型双系统（保 stock 留退路，`switch_to_stock.sh` + `set_miwifi_uboot_partition.sh`）
- CR 系列：激进型破坏性刷机（一次到位，OpenWrt 即终态）

**设计理由**（用户原话）："CR系列我们不打算双系统，而是破坏性刷机，刷openwrt后不可逆"

→ 维护者**不要**给 CR 项目加双系统逻辑，跟 ax6 模式不同！
