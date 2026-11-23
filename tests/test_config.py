"""
配置管理模块测试
"""

import os
import json
import tempfile
import pytest
from pathlib import Path

from videocut.config import Config, LLMConfig, LicenseCache, ConfigManager


class TestConfig:
    """Config 类测试"""

    def test_default_values(self):
        """默认值"""
        config = Config()

        assert config.license_key is None
        assert config.output_mode == "local"
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"

    def test_to_dict(self):
        """转换为字典"""
        config = Config(
            license_key="VC-TEST-1234",
            output_mode="jianying"
        )

        data = config.to_dict()

        assert data["license_key"] == "VC-TEST-1234"
        assert data["output_mode"] == "jianying"
        assert "llm" in data
        assert "license_cache" in data

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "license_key": "VC-TEST-5678",
            "device_id": "test-device",
            "output_mode": "local",
            "llm": {
                "provider": "anthropic",
                "model": "claude-3",
                "base_url": None
            },
            "jianying_path": None,
            "license_cache": {
                "valid": True,
                "expires_at": "2027-12-31",
                "cached_at": None
            }
        }

        config = Config.from_dict(data)

        assert config.license_key == "VC-TEST-5678"
        assert config.llm.provider == "anthropic"
        assert config.license_cache.valid is True


class TestLLMConfig:
    """LLMConfig 类测试"""

    def test_default_provider(self):
        """默认提供商"""
        config = LLMConfig()

        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.base_url is None

    def test_compatible_provider(self):
        """兼容服务配置"""
        config = LLMConfig(
            provider="compatible",
            base_url="https://api.example.com/v1",
            model="custom-model"
        )

        assert config.provider == "compatible"
        assert config.base_url == "https://api.example.com/v1"


class TestLicenseCache:
    """LicenseCache 类测试"""

    def test_default_invalid(self):
        """默认无效"""
        cache = LicenseCache()

        assert cache.valid is False
        assert cache.expires_at is None

    def test_valid_cache(self):
        """有效缓存"""
        cache = LicenseCache(
            valid=True,
            expires_at="2027-12-31"
        )

        assert cache.valid is True
        assert cache.expires_at == "2027-12-31"


class TestConfigManager:
    """ConfigManager 类测试"""

    def test_save_and_load(self, tmp_path, monkeypatch):
        """保存和加载"""
        import videocut.config as config_module

        config_dir = tmp_path / ".videocut"
        config_file = config_dir / "config.json"

        # 使用 monkeypatch 替换模块级常量
        monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)

        manager = ConfigManager()
        manager._config = None  # 清除可能的缓存

        # 创建配置
        config = Config(
            license_key="VC-TEST-SAVE",
            output_mode="jianying"
        )

        # 保存
        manager.save(config)

        assert config_file.exists()

        # 重新加载
        manager._config = None  # 清除缓存
        loaded = manager.load()

        assert loaded.license_key == "VC-TEST-SAVE"
        assert loaded.output_mode == "jianying"

    def test_is_initialized(self, tmp_path, monkeypatch):
        """检查是否初始化"""
        import videocut.config as config_module

        config_dir = tmp_path / ".videocut"
        config_file = config_dir / "config.json"

        # 使用 monkeypatch 替换模块级常量
        monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)

        manager = ConfigManager()
        manager._config = None

        # 未初始化（文件不存在）
        assert manager.is_initialized() is False

        # 初始化（保存配置）
        config = Config(license_key="VC-TEST")
        manager.save(config)
        manager._config = None  # 清除缓存

        assert manager.is_initialized() is True
