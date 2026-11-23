"""
配置管理模块

管理 ~/.videocut/ 下的配置文件
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime

from .utils.crypto import encrypt, decrypt
from .utils.device import get_device_id


# 配置目录
CONFIG_DIR = Path.home() / ".videocut"
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDENTIALS_FILE = CONFIG_DIR / ".credentials"


@dataclass
class LLMConfig:
    """LLM 服务配置"""
    provider: str = "openai"  # openai | anthropic | compatible
    base_url: Optional[str] = None  # 仅 compatible 时使用
    model: str = "gpt-4o"


@dataclass
class LicenseCache:
    """License 缓存"""
    valid: bool = False
    expires_at: Optional[str] = None
    cached_at: Optional[str] = None


@dataclass
class Config:
    """主配置"""
    license_key: Optional[str] = None
    device_id: str = field(default_factory=get_device_id)
    output_mode: str = "local"  # local | jianying
    llm: LLMConfig = field(default_factory=LLMConfig)
    jianying_path: Optional[str] = None
    license_cache: LicenseCache = field(default_factory=LicenseCache)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """从字典创建"""
        if "llm" in data and isinstance(data["llm"], dict):
            data["llm"] = LLMConfig(**data["llm"])
        if "license_cache" in data and isinstance(data["license_cache"], dict):
            data["license_cache"] = LicenseCache(**data["license_cache"])
        return cls(**data)


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self._config: Optional[Config] = None
        self._credentials: Dict[str, str] = {}  # 加密存储的凭证

    def _ensure_dir(self):
        """确保配置目录存在"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> Config:
        """
        加载配置

        如果配置文件不存在，返回默认配置
        """
        if self._config is not None:
            return self._config

        self._ensure_dir()

        # 加载主配置
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._config = Config.from_dict(data)
        else:
            self._config = Config()

        # 加载凭证
        if CREDENTIALS_FILE.exists():
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                self._credentials = json.load(f)

        return self._config

    def save(self, config: Optional[Config] = None):
        """保存配置"""
        if config is not None:
            self._config = config

        if self._config is None:
            return

        self._ensure_dir()

        # 保存主配置
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)

        # 保存凭证
        if self._credentials:
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, indent=2)

    def get_api_key(self, provider: str) -> Optional[str]:
        """
        获取 API Key（解密）

        Args:
            provider: 提供商名称 (openai/anthropic/compatible)
        """
        key = f"api_key_{provider}"
        encrypted = self._credentials.get(key)
        if encrypted:
            return decrypt(encrypted)
        return None

    def set_api_key(self, provider: str, api_key: str):
        """
        保存 API Key（加密）

        Args:
            provider: 提供商名称
            api_key: API Key 明文
        """
        key = f"api_key_{provider}"
        self._credentials[key] = encrypt(api_key)
        self.save()

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        config = self.load()
        return config.license_key is not None

    def update_license_cache(self, valid: bool, expires_at: Optional[str] = None):
        """更新 License 缓存"""
        config = self.load()
        config.license_cache.valid = valid
        config.license_cache.expires_at = expires_at
        config.license_cache.cached_at = datetime.now().isoformat()
        self.save()

    def is_license_cache_valid(self, max_age_hours: int = 24) -> bool:
        """
        检查 License 缓存是否有效

        Args:
            max_age_hours: 最大缓存时间（小时）
        """
        config = self.load()
        cache = config.license_cache

        if not cache.valid or not cache.cached_at:
            return False

        # 检查缓存时间
        cached_time = datetime.fromisoformat(cache.cached_at)
        age_hours = (datetime.now() - cached_time).total_seconds() / 3600

        return age_hours < max_age_hours


# 全局配置管理器实例
config_manager = ConfigManager()


if __name__ == "__main__":
    # 测试
    manager = ConfigManager()
    config = manager.load()

    print(f"配置目录: {CONFIG_DIR}")
    print(f"已初始化: {manager.is_initialized()}")
    print(f"设备ID: {config.device_id}")
    print(f"输出模式: {config.output_mode}")

    # 测试 API Key 加密存储
    manager.set_api_key("test", "sk-test-12345")
    retrieved = manager.get_api_key("test")
    print(f"API Key 加密存储测试: {'通过' if retrieved == 'sk-test-12345' else '失败'}")
