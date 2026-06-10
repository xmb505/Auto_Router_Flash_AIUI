#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载模块
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """配置管理类"""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件"""
        # 查找配置文件（优先从 src 目录）
        base_dir = Path(__file__).parent
        config_paths = [
            base_dir / "config.yaml",           # src/config.yaml (优先)
            base_dir.parent / "config.yaml",    # 项目根目录
            base_dir.parent / "config.yaml.example",
            Path("/etc/router-flash/config.yaml"),
        ]

        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break

        # 如果找不到配置文件，使用示例文件
        if config_file is None:
            example_path = base_dir.parent / "config.yaml.example"
            if example_path.exists():
                config_file = example_path
            else:
                self._config = self._default_config()
                return

        # 加载 YAML 配置
        with open(config_file, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def _default_config(self) -> Dict[str, Any]:
        """默认配置"""
        return {
            'global': {
                'log_enabled': True,
                'ping_interval': 1
            },
            'cr660x': {
                'firmware_dir': './firmware/cr660x',
                'initramfs': 'sharewifi_initramfs-kernel.bin',
                'sysupgrade': 'sharewifi_1.0.7.bin',
                'bootloader': 'pb-boot.img',
                'exploit_wifi': {
                    'ssid': 'MICR6608',
                    'password': '12345678'
                },
                'detect_ips': ['192.168.10.1', '192.168.2.1', '192.168.31.1'],
                'stage2_wait_ip': '192.168.1.1',
                'final_ip': '10.11.12.1',
                'ssh': {
                    'timeout': 30,
                    'retry_interval': 5,
                    'max_retries': 100
                },
                'min_memory': 248848,
                'uboot_ip': '192.168.1.1',
                'uboot_kernel': 'sharewifi_initramfs-kernel.bin'
            },
            'jgc': {
                'firmware_dir': './firmware/jgc',
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
                    'share_path': './firmware/jgc'
                },
                'pdcn_auth': {
                    'username': 'admin',
                    'password': 'admin'
                }
            },
            'inventory': {
                'mac_file': './firmware/mac_list.txt'
            }
        }

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号访问"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_firmware_path(self, category: str, filename: str) -> str:
        """获取固件完整路径"""
        mapping = {
            'cr660x': ('cr660x', 'firmware_dir', './firmware/cr660x'),
            'jgc': ('jgc', 'firmware_dir', './firmware/jgc'),
            'ax3000t': ('ax3000t', 'firmware_dir', './ax3000t/firmware'),
            'ax3600': ('ax3600', 'firmware_dir', './ax3600/firmware'),
        }
        if category in mapping:
            section, key, default = mapping[category]
            base_dir = self._config.get(section, {}).get(key, default)
        else:
            base_dir = './'

        base_dir = Path(__file__).parent / base_dir
        return str(base_dir / filename)

    @property
    def cr660x(self) -> Dict[str, Any]:
        """获取 CR660X 配置"""
        return self._config.get('cr660x', {})

    @property
    def jgc(self) -> Dict[str, Any]:
        """获取 JGC 配置"""
        return self._config.get('jgc', {})

    @property
    def ax3000t(self) -> Dict[str, Any]:
        """获取 AX3000T 配置"""
        return self._config.get('ax3000t', {})

    @property
    def inventory(self) -> Dict[str, Any]:
        """获取存货配置"""
        return self._config.get('inventory', {})

    @property
    def global_settings(self) -> Dict[str, Any]:
        """获取全局设置"""
        return self._config.get('global', {})


# 全局配置实例
config = Config()
