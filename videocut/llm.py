"""
LLM 统一接口模块

支持 OpenAI、Anthropic 和 OpenAI 兼容服务
"""

from typing import Dict, Any, Optional


def test_llm_connection(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    测试 LLM 服务连接

    Args:
        provider: 提供商 (openai/anthropic/compatible)
        api_key: API Key
        model: 模型名称
        base_url: API Base URL (仅 compatible 需要)

    Returns:
        {"success": True/False, "error": "错误信息"}
    """
    try:
        if provider == "openai":
            return _test_openai(api_key, model)
        elif provider == "anthropic":
            return _test_anthropic(api_key, model)
        elif provider == "compatible":
            return _test_compatible(api_key, model, base_url)
        else:
            return {"success": False, "error": f"未知提供商: {provider}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _test_openai(api_key: str, model: str) -> Dict[str, Any]:
    """测试 OpenAI 连接"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5
        )

        if response.choices:
            return {"success": True}
        else:
            return {"success": False, "error": "无响应"}

    except Exception as e:
        error_msg = str(e)
        if "invalid_api_key" in error_msg.lower() or "401" in error_msg:
            return {"success": False, "error": "API Key 无效"}
        elif "model" in error_msg.lower():
            return {"success": False, "error": f"模型 {model} 不可用"}
        return {"success": False, "error": error_msg}


def _test_anthropic(api_key: str, model: str) -> Dict[str, Any]:
    """测试 Anthropic 连接"""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}]
        )

        if response.content:
            return {"success": True}
        else:
            return {"success": False, "error": "无响应"}

    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "401" in error_msg:
            return {"success": False, "error": "API Key 无效"}
        elif "model" in error_msg.lower():
            return {"success": False, "error": f"模型 {model} 不可用"}
        return {"success": False, "error": error_msg}


def _test_compatible(api_key: str, model: str, base_url: str) -> Dict[str, Any]:
    """测试 OpenAI 兼容服务连接"""
    if not base_url:
        return {"success": False, "error": "需要提供 Base URL"}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5
        )

        if response.choices:
            return {"success": True}
        else:
            return {"success": False, "error": "无响应"}

    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "401" in error_msg:
            return {"success": False, "error": "API Key 无效"}
        elif "connect" in error_msg.lower():
            return {"success": False, "error": f"无法连接到 {base_url}"}
        return {"success": False, "error": error_msg}


class LLMClient:
    """
    LLM 统一调用客户端
    """

    def __init__(self, provider: str, api_key: str, model: str, base_url: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        """获取或创建客户端"""
        if self._client is not None:
            return self._client

        if self.provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)

        elif self.provider == "anthropic":
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)

        elif self.provider == "compatible":
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        return self._client

    def chat(self, messages: list, max_tokens: int = 4096) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            max_tokens: 最大返回 token 数

        Returns:
            模型响应文本
        """
        client = self._get_client()

        if self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages
            )
            return response.content[0].text

        else:  # openai 或 compatible
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content


def get_llm_client() -> LLMClient:
    """
    获取配置好的 LLM 客户端

    从配置文件读取设置
    """
    from .config import config_manager

    config = config_manager.load()
    api_key = config_manager.get_api_key(config.llm.provider)

    if not api_key:
        raise ValueError("未配置 API Key，请运行 videocut init")

    return LLMClient(
        provider=config.llm.provider,
        api_key=api_key,
        model=config.llm.model,
        base_url=config.llm.base_url
    )
