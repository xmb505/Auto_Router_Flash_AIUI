#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载模块
"""

import os
import yaml
from pathlib import Path

class Config:
    """配置管理类"""

    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件"""
        # 查找配置文件
        config_paths = [
            Path(__file__).parent / "config.yaml",
            Path(__file__).parent.parent / "config.yaml",
            Path("/etc/router-flash/config.yaml"),
        ]

        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break

        # 如果找不到配置文件，使用示例文件
        if config_file is None:
            example_path = Path(__file__).parent.parent / "config.yaml.example"
            if example_path.exists():
                config_file = example_path
            else:
                # 使用默认配置
                self._config = self._default_config()
                return

        # 加载 YAML 配置
        with open(config_file, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def _default_config(self):
        """默认配置"""
        return {
            'global': {
                'log_enabled': True
            },
            'cr660x': {
                'firmware_dir': './CR660X',
                'initramfs': 'sharewifi_initramfs-kernel.bin',
                'sysupgrade': 'sharewifi_1.0.7.bin',
                'bootloader': 'pb-boot.img',
                'ap_ssid': 'ShareWiFi_5G',
                'ap_password': '12345678',
                'detect_ips': ['192.168.10.1', '192.168.2.1', '192.168.31.1'],
                'stage2_wait_ip': '192.168.1.1',
                'final_ip': '10.11.12.1',
                'ssh': {
                    'timeout': 30,
                    'retry_interval': 5,
                    'max_retries': 100
                },
                'min_memory': 248848
            },
            'jgc': {
                'firmware_dir': './JGC-Q10',
                'pdcn_firmware': 'JCG-Q20-PDCN.bin',
                'bootloader': 'pb-boot.img',
                'final_firmware': 'sharewifi_1.0.7.bin',
                'detect_ips': {
                    'official': '192.168.10.1',
                    'official_qx': '192.168.2.1',
                    'pdcn': '192.168.123.1',
                    'uboot': '192.168.1.1',
                    'final': '10.11.12.1'
                },
                'chfs': {
                    'port': 8080,
                    'share_path': './JGC-Q10'
                },
                'pdcn_auth': {
                    'username': 'admin',
                    'password': 'admin'
                }
            },
            'network': {
                'rp_filter': 0
            },
            'inventory': {
                'mac_file': './mac_list.txt'
            }
        }

    def get(self, key, default=None):
        """获取配置项"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    @property
    def cr660x(self):
        """获取 CR660X 配置"""
        return self._config.get('cr660x', {})

    @property
    def jgc(self):
        """获取 JGC 配置"""
        return self._config.get('jgc', {})

    @property
    def inventory(self):
        """获取存货配置"""
        return self._config.get('inventory', {})

    @property
    def global_settings(self):
        """获取全局设置"""
        return self._config.get('global', {})


# 全局配置实例
config = Config()
