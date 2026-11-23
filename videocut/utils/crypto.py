"""
加密工具模块

用于加密存储敏感信息（API Key 等）
"""

import base64
import hashlib
from cryptography.fernet import Fernet

from .device import get_device_id


def _get_key() -> bytes:
    """
    基于设备ID生成加密密钥

    同一设备上密钥相同，不同设备密钥不同
    """
    device_id = get_device_id()
    # 使用 SHA256 生成 32 字节密钥，然后 base64 编码为 Fernet 需要的格式
    key_bytes = hashlib.sha256(device_id.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def encrypt(plaintext: str) -> str:
    """
    加密字符串

    Args:
        plaintext: 明文字符串

    Returns:
        加密后的 base64 字符串
    """
    if not plaintext:
        return ""

    key = _get_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt(ciphertext: str) -> str:
    """
    解密字符串

    Args:
        ciphertext: 加密后的 base64 字符串

    Returns:
        解密后的明文字符串
    """
    if not ciphertext:
        return ""

    key = _get_key()
    f = Fernet(key)
    decrypted = f.decrypt(ciphertext.encode())
    return decrypted.decode()


if __name__ == "__main__":
    # 测试
    test_text = "sk-test-api-key-12345"
    print(f"原文: {test_text}")

    encrypted = encrypt(test_text)
    print(f"加密: {encrypted}")

    decrypted = decrypt(encrypted)
    print(f"解密: {decrypted}")

    print(f"验证: {'通过' if test_text == decrypted else '失败'}")
