"""
设备ID生成模块

生成稳定的设备唯一标识，用于 License 绑定
"""

import platform
import uuid
import hashlib


def get_device_id() -> str:
    """
    生成设备唯一标识

    基于 MAC 地址和系统信息生成，同一设备上稳定不变
    """
    # 获取 MAC 地址
    mac = uuid.getnode()

    # 获取系统信息
    system_info = f"{platform.system()}-{platform.machine()}-{platform.node()}"

    # 组合并哈希
    raw = f"{mac}-{system_info}"
    device_id = hashlib.sha256(raw.encode()).hexdigest()[:32]

    return device_id


def get_device_name() -> str:
    """
    获取设备友好名称

    如: "MacBook Pro (macOS)"
    """
    node = platform.node()
    system = platform.system()

    # 简化显示
    if system == "Darwin":
        system = "macOS"

    return f"{node} ({system})"


if __name__ == "__main__":
    # 测试
    print(f"Device ID: {get_device_id()}")
    print(f"Device Name: {get_device_name()}")
