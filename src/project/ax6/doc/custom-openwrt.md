# 7.custom_openwrt.py — 应用自定义 overlay

## 用途

往已刷好 ImmortalWrt/OpenWrt 的路由器上传一个 `.tar.gz` overlay 包，覆盖主题、配置、附加软件等个性化内容，然后自动重启。

## 适用场景

- 套用现成的"主题包"（自定义 LuCI 主题、首页 logo 等）
- 批量刷入 `etc/config/*` 配置（无需手敲 UCI）
- 安装预打包的 `ipk` 到 `/overlay/upper/`，重启后即生效

## 与小米 SSH 工具的关系

不复用 `miwifi_ssh.sh`。OpenWrt 用 ED25519 host key、root 空密码，
脚本里直接走 `sshpass + scp/ssh`，不走小米的 ssh 工具层。

## overlay 包格式

`tar.gz` 解压后**必须是 `overlay/` 顶层目录**，脚本会执行：
```
cp -a overlay/* /overlay/upper/
```

打包示例：
```bash
tar -czf overlay-new.tar.gz -C /path/to/files overlay
```

## 使用

```bash
# 默认 (OpenWrt 192.168.1.1 + 默认密码)
python3 ./7.custom_openwrt.py --file files/overlay-new.tar.gz

# 显式 IP / 自定义 SSH 密码
python3 ./7.custom_openwrt.py --ip 192.168.1.1 --ssh-pwd mypass --file my.tar.gz
```

## 内部流程

1. **scp** 上传：`files/overlay-new.tar.gz` → `/tmp/overlay-new.tar.gz`
2. **SSH** 解压合并：
   ```
   cd /tmp && tar -xzf overlay-new.tar.gz \
     && cp -a overlay/* /overlay/upper/ \
     && rm -rf overlay overlay-new.tar.gz \
     && echo OK
   ```
3. **SSH** 触发 `reboot`（连接中断是预期，不报错）
4. 输出 JSON

## 输出 JSON（成功）

```json
{
  "ok": true,
  "step": "custom_openwrt",
  "data": {
    "ip": "192.168.1.1",
    "file": "files/overlay-new.tar.gz",
    "remote_path": "/tmp/overlay-new.tar.gz",
    "extract_marker": "OK",
    "reboot": true
  }
}
```

## 退出码

| Code | 含义 |
|------|------|
| `0` | 成功 |
| `2` | 参数/本地文件不存在 |
| `3` | scp/网络失败 |
| `4` | SSH 认证失败（密码错） |
| `1` | 解压失败 / 通用错误 |

## 前提

- 路由器**已**刷好 ImmortalWrt/OpenWrt（mtd 上有 OpenWrt rootfs）
- SSH 可达 root（默认免密）
- overlay 包结构合法（顶层 `overlay/` 目录）

## 验证

刷完后等路由器重启完毕，访问 LuCI 看主题/配置是否生效，或 SSH 进去 `ls /overlay/upper/` 检查文件落地。