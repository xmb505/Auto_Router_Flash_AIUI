# switch_to_stock.sh — 切到 mtd12 (rootfs) 分区

## 用途

在不拆机、不接 UART 的前提下，从当前系统切到 mtd12（rootfs）分区。
不假定 mtd12 是原厂——只切启动 flag，不判断内容。

## 原理

两行 `fw_setenv` 写 uboot env 标志位，让下次启动走 mtd12（rootfs）：

```bash
fw_setenv flag_try_sys1_failed 0
fw_setenv flag_boot_rootfs 0
reboot
```

OpenWrt 下 `fw_setenv` 和 stock 下 `nvram` 写的是同一个 NAND 分区，效果等价。

## 使用

```bash
./switch_to_stock.sh                    # 默认 192.168.1.1
./switch_to_stock.sh --ip 192.168.1.1   # 指定 IP
```

输出 JSON，exit 0 = 成功。

## 切完后

路由器重启进入 mtd12，IP 取决于那个分区实际装了什么系统。
如果 mtd12 是小米 stock，IP 回到 `192.168.31.1`。

## 前提

- mtd12 上需要有一个可启动的系统（刷 OpenWrt 时烧到对侧 mtd 的话，mtd12 可能还是原厂）
- SSH 免密登录（ImmortalWrt 默认 root 无密码）
