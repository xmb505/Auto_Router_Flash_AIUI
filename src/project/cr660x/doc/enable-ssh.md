# CR660X — 启用 SSH

> 适用机型：CR6606 / CR6608 / CR6609 / TR606 / TR608 / TR609（MT7621A）
> 已实机验证：CR6608 1.0.100（移动版）、CR6606 1.0.117（联通版）

## 漏洞：CVE-2023-26319（smartcontroller scene 注入）

smart home scene executor 的 `wan_block` 动作中 `mac` 字段无转义拼进 `system()`，触发场景即可执行任意命令。

```
// cmdbuf = /usr/sbin/sysapi macfilter set mac=<注入点> wan=no;...
sprintf(&cmdbuf, "/usr/sbin/sysapi macfilter set mac=%s wan=%s;...", mac, wan);
return run_cmd(&cmdbuf);  // `mac` directly injected into system()!
```

## 注入方式

### 第一步：热身（激活 smartcontroller 服务）

smartcontroller 是懒启动的。需要通过 `set_sys_time` 写 `/tmp/ntp.status` 来唤醒：

```bash
python3 3.enable_ssh.py --ip <IP> --stok <stok>
```

脚本内部流程：

1. **hackCheck 探测** — 确定分隔符用 `;` 还是 `\n`
2. **读取原系统时间** — 备份当前时间
3. **热身** — `set_sys_time` 写入 `/tmp/ntp.status`，触发 smartcontroller 懒启动
4. **32 秒激活循环** — 每 2s 注入 `date -s 203301020304`，读 `sys_time` 验证链路
5. **时间变了** → 链路通，恢复原时间

### 第二步：注入命令

链路验证通过后，通过两种粒度注入：

| 函数 | 适用 | 原理 |
|------|------|------|
| `exec_tiny_cmd` | ≤23 字节命令 | 直接拼到 `mac` 字段：`;COMMAND;` |
| `exec_cmd` | 任意长命令 | 分块 `echo -n` 写入 `/tmp/e` → `chmod +x` → `sh /tmp/e` |

### 第三步：SSH 启用序列

```
nvram set ssh_en=1 ; nvram commit
echo root >/tmp/x ; echo root >>/tmp/x ; passwd root </tmp/x
sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear
/etc/init.d/dropbear enable
/etc/init.d/dropbear restart
```

### 第四步：TCP 探测 22 端口

最多 11 次 × 3s 间隔等待 dropbear 启动。

### 成功标志

```bash
sshpass -p root ssh -oHostKeyAlgorithms=+ssh-rsa \
  -oStrictHostKeyChecking=no \
  -oUserKnownHostsFile=/dev/null \
  root@192.168.10.1 "id"

# uid=0(root) gid=0(root)
```

## 关键认知（基于 2026-06-11 实测）

### `get_scene_setting` 失败 ≠ 注入不可用

| API | CR6608 1.0.100 响应 | 含义 |
|-----|---------------------|------|
| `scene_setting` | `{"code":0,"msg":"","id":1}` | ✅ 创建场景成功 |
| `scene_start_by_crontab` | `{"code":0,"msg":""}` | ✅ 触发成功 |
| `get_scene_setting` | `{"code":-100,"msg":"connect failed"}` | 场景**列表查询**不可用，**不影响注入** |

`get_scene_setting` 是对 smartcontroller 服务的查询接口，返回 `code:-100` 只能说明列表查询功能坏了（或无场景存在），**不代表** `scene_setting` 和 `scene_start_by_crontab` 不可用。

### 必须热身

直接 `scene_setting` → `scene_start_by_crontab` 不热身时，API 返回 `code:0` 但命令**不执行**（时间不变）。必须先走 `set_sys_time` 写 `/tmp/ntp.status` 唤醒 smartcontroller 服务，再等 32s 激活。

### 固件差异：CR6608 1.0.100 vs CR6606 1.0.117

| 维度 | CR6608 1.0.100 | CR6606 1.0.117 |
|------|---------------|---------------|
| smartcontroller | 懒启动，需热身 | 同 |
| `set_config_iotdev` -h | `code:1523`（封锁） | 未测 |
| `c_upload` | `code:1629`（完全不可用） | 未测 |
| `arn_switch` | `code:0` 假阳性 | 未测 |
| SSH | root/root | root/root |
| dropbear host key | ssh-rsa | ssh-rsa |

### 恢复出厂后必须重新跑

恢复出厂后路由器 `inited` 变成 `1`（移动版自动初始化），需要用**迁移后的密码**重新登录获取 stok，再跑 `3.enable_ssh.py`。

## 链式调用

```bash
# 独立运行
python3 3.enable_ssh.py --ip 192.168.10.1 --stok <stok>

# 管道流
python3 2.login_get_stok.py --pwd <password> | python3 3.enable_ssh.py
```

## 实战教训：第一次为什么没注入成功（2026-06-11）

**表面现象**：`3.enable_ssh.py` 跑完 smartcontroller 链路验证成功（时间变 2033），nvram/passwd 也都注入了，但 SSH 端口 22 始终不开。

**根因**：超时 120s 不够。

`exec_cmd` 把长命令拆成多个 `echo -n` 场景注入——每个分块都要走 `scene_setting` → `scene_start_by_crontab` → `scene_delete` 三步，单块约 5-8 秒。`sed`、`dropbear enable`、`dropbear restart` 三条 `exec_cmd` 拆出几十个分块：

| 操作 | 耗时 |
|------|------|
| `sed -i 's/release/...' /etc/init.d/dropbear` | ~50s |
| `/etc/init.d/dropbear enable` | ~30s |
| `/etc/init.d/dropbear restart` | ~33s |
| TCP 探测（最多 11×3s 等待） | ~15-48s |
| **总计** | **~150-160s** |

第一次跑时 timeout 120s 在 `dropbear restart` 刚触发时就到了——`sed` 分块写入未完成，`/etc/init.d/dropbear` 里 `release` 检查没改干净，dropbear 被锁住起不来。

**修复**：timeout 改 240s，第二次就跑通了。

**经验**：smartcontroller 的 `exec_cmd` 分块注入非常慢。以后写新脚本用到 `exec_cmd` 时，默认 timeout 至少给 **4 分钟**。

## 禁用路径（本机型不适用）

以下 API 在 CR6608 1.0.100 上**不可用**：

- `set_config_iotdev` ssid `-h` 注入 → `code:1523`
- `c_upload` + `netspeed` XML 注入 → `code:1629`（拒绝所有上传）
- `arn_switch` / `start_binding` / `set_mac_filter` / `datacenter7` → 不执行命令

**只走 smartcontroller scene 注入。**
