# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working on this repository.

## Project Status

| Component | Status | Notes |
|-----------|--------|-------|
| `src/cr660x/flasher.py` | Working | 3-step flash tested; CR660X Step 3 (uboot HTTP upload) verified |
| `src/jgc/flasher.py` | ⚠️ Untested | Reference only — old `JGC-Q*/` scripts are proven |
| `src/main.py` | Working | TUI operational; CR660X flow tested |
| Old scripts (`CR660X/`, `JGC-Q*/`) | Stable | Reference implementations |

## Project Overview

Semi-automated router flashing pipeline for batch-flashing routers with custom firmware (shareWiFi). Targets two router families:

- **CR660X** (Xiaomi/China Unicom) — 3-step flash: Official → Bootloader+Kernel → Final Firmware
- **JGC-Q10/Qx** (JCG Q20 series) — 3-step flash: Official → PDCN → Bootloader → Final Firmware

All new development happens in `src/`. Old scripts are **reference only**.

## Running the Program

### Dependencies (Alpine Linux)

```bash
# System packages
apk add ping sshpass openssh-client python3 py3-pip

# Python packages
pip install requests rich scapy
```

### Run

```bash
cd /home/xmb505/alpine-router-flash/src
python3 main.py
```

The `src/` directory is self-contained and can be copied independently.

### Syntax Check

```bash
cd /home/xmb505/alpine-router-flash/src
python3 -m py_compile main.py cr660x/flasher.py jgc/flasher.py config.py utils.py
```

## Architecture

### Directory Layout

```
src/
├── main.py              # TUI entry point (screens + flow orchestration)
├── config.py            # Singleton config loader (YAML)
├── config.yaml          # Runtime configuration
├── utils.py             # NetworkTool, ShellTool, CryptoTool, WaitTool
├── cr660x/flasher.py    # CR660XFlasher (3-step flash)
├── jgc/flasher.py       # JGCFlasher (3-step flash)
└── firmware/
    ├── cr660x/         # pb-boot.img, initramfs, sysupgrade
    └── jgc/            # JGC firmware + chfs binary
```

## CR660X Flashing Flow

### Step 1: Official System → Bootloader + Kernel (Mobile/Telecom)

```
detect_router() → login(password) → enable_ssh(stok) → open_ssh_channel(stok)
→ upload_files(password) → flash_bootloader() → flash_initramfs()
```

### Step 1: Official System → Bootloader + Kernel (Unicom/联通)

```
detect_router() → login_unicom() → get_sn(stok) → calc_unicom_root_password(sn)
→ enable_ssh(stok) → open_ssh_channel(stok)
→ upload_files(root_password) → flash_bootloader(root_password) → flash_initramfs(root_password)
```

**联通版关键差异：**
- 使用 GET 请求登录（移动版用 POST）
- stok 从 `token` 字段提取（移动版从 `url` 字段）
- 需要从 `/api/misystem/newstatus` 获取 SN
- 根据 SN 计算 root 密码：`MD5(SN + salt)[:8]`
- SN 包含 "/" 时使用 `others_salt`，否则使用 `r1d_salt`
- SSH 使用计算出的 root 密码（移动版用用户输入的密码）

### Step 2: Initramfs → Final Firmware

```
wait 192.168.1.1 online → verify SSH (up to 2 min) → check memory (≥248848 KB)
→ SCP upload → sysupgrade → wait 192.168.1.1 offline
```

### Step 3: Uboot → Kernel (NEW)

```
wait 192.168.1.1 online → POST /upload.cgi (multipart) → poll /status.html → GET /reboot.cgi
→ auto-enter Step 2
```

**Key behaviors:**
- `enable_ssh()` exploits `extendwifi_connect` API with **60s timeout**
- `open_ssh_channel()` calls `oneclick_get_remote_token` with **60s timeout**
- `sysupgrade` causes SSH disconnect — this is **normal**, treat as success
- Step 2 verifies SSH to distinguish initramfs from uboot (both use 192.168.1.1)
- Step 2 now waits for **192.168.1.1 to go offline** (faster feedback) instead of waiting for final_ip

## JGC Flashing Flow

### Step 1: Official → PDCN
```
detect_password() → get_stok() → upload_firmware() → confirm_upgrade()
```

### Step 2: PDCN → Bootloader
```
chfs auto-start → wget pb-boot.img → mtd_write → reboot
```
- PDCN command execution via `POST /apply.cgi` with Basic Auth `admin:admin`

### Step 3: Uboot → Final Firmware
```
POST /upload.cgi → poll /status.html → GET /reboot.cgi
```
- Uboot httpd returns non-standard HTTP — handle `BadStatusLine`

## TUI Flow

```
CR660X Main Menu (3 options)
  ├─ [1] Official → Bootloader+Kernel → Stage 2
  ├─ [2] OpenWRT upgrade (Stage 2 only)
  └─ [3] Uboot upload kernel → auto-enter Stage 2

JGC Main Menu (3 steps, any can start)
  ├─ [1] Official → PDCN
  ├─ [2] PDCN → Bootloader
  └─ [3] Bootloader → Final Firmware
```

Press `r` in CR660X menu to re-detect IP.

## Authentication

### CR660X (SHA1 auth)
```python
first_hash = SHA1(password + key)       # key from /cgi-bin/luci/web
old_pwd = SHA1(nonce + first_hash)    # nonce = "0_{device_id}_{timestamp}_{random}"
```
- POST to `/cgi-bin/luci/api/xqsystem/login`
- Returns stok in URL field

### JGC (Base64 auth)
```python
auth = Base64("root:password")
```
- Login returns stok + sysauth cookie
- PDCN uses Basic Auth `admin:admin`

## Network Topology

Alpine LXC container with 5 virtual NICs on the same L2 bridge:

| Subnet | Container IP | Stage |
|--------|-------------|-------|
| 192.168.1.0/24 | 192.168.1.5 | uboot / initramfs |
| 192.168.2.0/24 | 192.168.2.5 | JGC-Qx official |
| 192.168.10.0/24 | 192.168.10.5 | JGC-Q10 / Xiaomi |
| 192.168.31.0/24 | 192.168.31.5 | Xiaomi default |
| 192.168.123.0/24 | 192.168.123.5 | PDCN system |

**Critical:** `sysctl net.ipv4.conf.all.rp_filter` must be 0 or 2.

**PVE host optimization:** For faster ARP cache refresh on IP changes:
```bash
# Add to /etc/sysctl.conf on PVE host
net.ipv4.neigh.default.base_reachable_time_ms = 5000
net.ipv4.neigh.default.gc_stale_time = 5
net.ipv4.neigh.default.retrans_time_ms = 500
sysctl -p
```

## Configuration

Config is loaded with fallback: `src/config.yaml` → `config.yaml` → `config.yaml.example` → hardcoded defaults.

### Key Settings

```yaml
global:
  ping_interval: 0.5  # seconds, float supported

cr660x:
  detect_ips: [10.11.12.1, 192.168.1.1, 192.168.10.1, ...]
  min_memory: 248848  # KB, rejects 128MB routers
  uboot_ip: "192.168.1.1"
  uboot_kernel: "sharewifi_initramfs-kernel.bin"

jgc:
  detect_ips:
    final: "10.11.12.1"  # included in detection list
  chfs:
    ip: "192.168.123.5"
    port: 8080
```

## NetworkTool (utils.py)

`NetworkTool.ping()` uses **scapy ARP ping** by default (bypasses system ARP cache, ~0.001s). Falls back to system `ping` if scapy unavailable.

```python
NetworkTool.ping(host, timeout=1, use_arp=True)
NetworkTool.arp_ping(host, timeout=1)  # Direct ARP, no system cache
NetworkTool.get_mac(ip)  # Uses scapy ARP if available
```

`WaitTool.wait_for_ip()` supports float intervals from config's `ping_interval`.

## Known Nuances

1. **extendwifi_connect timeout**: Takes 30-60s. Always use `timeout=60`.
2. **oneclick_get_remote_token timeout**: Also 60s.
3. **sysupgrade SSH disconnect**: Normal behavior. Treat as success.
4. **uboot vs initramfs**: Both use 192.168.1.1. Step 2 verifies SSH (uboot has no SSH).
5. **SCP -O flag**: Required for OpenWRT/initramfs targets.
6. **Password validation**: CR660X requires exactly 8 characters.
7. **MAC tracking**: Constant across stages. Deduplicated via `recorded_macs`.
8. **OOM on large uploads**: Memory-constrained LXC containers may OOM when uploading large firmware. Avoid streaming uploads that lack Content-Length header.
9. **chfs process management**: `_jgc_ensure_chfs()` kills old chfs processes before starting new ones. Program exit also cleans up via `finally` block to prevent process accumulation.
