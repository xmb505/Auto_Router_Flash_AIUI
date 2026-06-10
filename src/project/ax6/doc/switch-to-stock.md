# switch_to_stock.sh — OpenWrt → 小米 stock

## 用途

在不拆机、不接 UART 的前提下，从 OpenWrt/ImmortalWrt 切回小米官方固件。

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

路由器重启进入小米 stock，IP 回到 `192.168.31.1`，固件版本和初始化状态不变。

## 前提

- mtd12 上还有可启动的小米固件（出厂就在那，刷 OpenWrt 时烧到对侧 mtd 的话就不会动它）
- SSH 免密登录（ImmortalWrt 默认 root 无密码）
