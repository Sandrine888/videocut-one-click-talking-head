"""
License 验证模块

在线验证 License 有效性，支持本地缓存

配置方式（任选其一）:
1. 环境变量（生产模式）:
   - VIDEOCUT_SUPABASE_URL: Supabase 项目 URL
   - VIDEOCUT_SUPABASE_ANON_KEY: Supabase anon key

2. Mock 模式（开发/测试）:
   - 设置 VIDEOCUT_LICENSE_MOCK=1
   - 或不配置 Supabase 环境变量
   - 以 VC-TEST 或 VC- 开头的 key 视为有效
"""

import os
import httpx
from typing import Dict, Any

from .config import config_manager
from .utils.device import get_device_id, get_device_name

# Supabase 配置（可通过环境变量覆盖）
SUPABASE_URL = os.environ.get(
    "VIDEOCUT_SUPABASE_URL",
    "https://osshzlvufywgyzoolqfd.supabase.co"
)
SUPABASE_ANON_KEY = os.environ.get(
    "VIDEOCUT_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9zc2h6bHZ1Znl3Z3l6b29scWZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njg2NTY5NjUsImV4cCI6MjA4NDIzMjk2NX0.VzEAVe-UBBZjA_YzcLCLfDJpX-Tn4SR51ZGRxgN8E2w"
)
VERIFY_FUNCTION = "verify-license"


def _is_mock_mode() -> bool:
    """判断是否使用 mock 模式（仅开发测试用）"""
    # 仅当显式设置 VIDEOCUT_LICENSE_MOCK=1 时才使用 mock
    return os.environ.get("VIDEOCUT_LICENSE_MOCK") == "1"


def _verify_license_online(license_key: str) -> Dict[str, Any]:
    """
    在线验证 License（调用 Supabase Edge Function）

    Args:
        license_key: License Key (VC-XXXX-XXXX-XXXX)

    Returns:
        {
            "valid": True/False,
            "expires_at": "2027-01-17",  # 如果有效
            "devices_used": 1,
            "devices_max": 2,
            "error": "错误信息"  # 如果无效
        }
    """
    device_id = get_device_id()
    device_name = get_device_name()

    # 构造请求
    url = f"{SUPABASE_URL}/functions/v1/{VERIFY_FUNCTION}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "license_key": license_key,
        "device_id": device_id,
        "device_name": device_name
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                data = response.json()

                # 更新缓存
                if data.get("valid"):
                    config_manager.update_license_cache(
                        valid=True,
                        expires_at=data.get("expires_at")
                    )

                return data

            else:
                return {
                    "valid": False,
                    "error": f"服务器错误: {response.status_code}"
                }

    except httpx.ConnectError:
        # 网络错误，尝试使用缓存
        if config_manager.is_license_cache_valid():
            config = config_manager.load()
            return {
                "valid": True,
                "expires_at": config.license_cache.expires_at,
                "cached": True
            }
        return {
            "valid": False,
            "error": "网络连接失败，且无有效缓存"
        }

    except Exception as e:
        return {
            "valid": False,
            "error": str(e)
        }


def _verify_license_mock(license_key: str) -> Dict[str, Any]:
    """
    模拟 License 验证（开发测试用）

    以 VC-TEST 开头的 key 视为有效
    以 VC- 开头的其他 key 也暂时视为有效（测试阶段）
    """
    if license_key.startswith("VC-TEST"):
        return {
            "valid": True,
            "expires_at": "2027-12-31",
            "devices_used": 1,
            "devices_max": 2
        }
    elif license_key.startswith("VC-"):
        # 其他 VC- 格式也暂时视为有效（测试阶段）
        return {
            "valid": True,
            "expires_at": "2027-12-31",
            "devices_used": 1,
            "devices_max": 2
        }
    else:
        return {
            "valid": False,
            "error": "License Key 格式错误（应以 VC- 开头）"
        }


def verify_license(license_key: str) -> Dict[str, Any]:
    """
    验证 License

    根据配置自动选择 mock 或在线验证:
    - 配置了 Supabase 环境变量 → 在线验证
    - 未配置或设置 VIDEOCUT_LICENSE_MOCK=1 → mock 验证
    """
    if _is_mock_mode():
        return _verify_license_mock(license_key)
    return _verify_license_online(license_key)


def check_license() -> Dict[str, Any]:
    """
    检查当前 License 状态

    优先使用缓存（24小时内有效），否则在线验证
    """
    config = config_manager.load()

    if not config.license_key:
        return {
            "valid": False,
            "error": "未配置 License"
        }

    # 检查缓存
    if config_manager.is_license_cache_valid():
        return {
            "valid": True,
            "expires_at": config.license_cache.expires_at,
            "cached": True
        }

    # 在线验证
    return verify_license(config.license_key)
