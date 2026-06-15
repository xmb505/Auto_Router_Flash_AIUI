#!/usr/bin/env python3
# calc_cr_unicom.py — 计算 CR660X 联通版 SSH root 密码
#
# 算法来源: old_coding/haku-cr660x-sidehackwifi/刷机/unicom_flash.sh
#           SN 含 "/" 用 others_salt (segments 反转), 否则用 r1d_salt
#           密码 = MD5(SN + salt)[:8]
#
# 用法: ./calc_cr_unicom.py --sn <SN>
# 输出: {"sn": "...", "salt": "...", "password": "..."}

import argparse
import hashlib

R1D_SALT = "A2E371B0-B34B-48A5-8C40-A7133F3B5D88"
OTHERS_SALT_RAW = "d44fb0960aa0-a5e6-4a30-250f-6d2df50a"
OTHERS_SALT = "-".join(OTHERS_SALT_RAW.split("-")[::-1])  # segments 反转


def calc_root_password(sn: str) -> dict:
    if not sn:
        raise ValueError("SN 不能为空")
    salt = OTHERS_SALT if "/" in sn else R1D_SALT
    pwd = hashlib.md5((sn + salt).encode()).hexdigest()[:8]
    return {"sn": sn, "salt": salt, "password": pwd}


def main():
    p = argparse.ArgumentParser(description="CR660X 联通版 SSH root 密码计算器")
    p.add_argument("--sn", required=True, help="路由器 SN (来自 /api/misystem/newstatus)")
    args = p.parse_args()
    result = calc_root_password(args.sn)
    print(f"SN:       {result['sn']}")
    print(f"SALT:     {result['salt']}")
    print(f"Password: {result['password']}")


if __name__ == "__main__":
    main()
