"""
config 命令实现

修改配置
"""

from rich.console import Console
from rich.prompt import Prompt, Confirm

from ..config import config_manager, LLMConfig

console = Console()


def run_config():
    """运行配置修改流程"""
    console.print("\n[bold]修改配置[/bold]")
    console.print("  [1] 修改 AI 服务配置")
    console.print("  [2] 修改默认输出方式")
    console.print("  [3] 返回")

    choice = Prompt.ask("请选择", choices=["1", "2", "3"], default="3")

    if choice == "1":
        _config_llm()
    elif choice == "2":
        _config_output()
    else:
        return


def _config_llm():
    """修改 LLM 配置"""
    config = config_manager.load()

    console.print("\n选择 LLM 提供商:")
    console.print("  [1] OpenAI")
    console.print("  [2] Anthropic (Claude)")
    console.print("  [3] OpenAI 兼容服务")

    provider_choice = Prompt.ask("请选择", choices=["1", "2", "3"], default="1")
    provider_map = {"1": "openai", "2": "anthropic", "3": "compatible"}
    provider = provider_map[provider_choice]

    base_url = None
    if provider == "compatible":
        base_url = Prompt.ask("请输入 API Base URL")

    api_key = Prompt.ask("请输入 API Key", password=True)

    model_defaults = {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "compatible": "deepseek-chat"
    }
    model = Prompt.ask("请输入模型名称", default=model_defaults[provider])

    # 测试连接
    console.print("\n⏳ 测试 AI 服务连接...")
    from ..llm import test_llm_connection
    result = test_llm_connection(provider, api_key, model, base_url)

    if not result["success"]:
        console.print(f"[red]✗ 连接失败：{result.get('error', '未知错误')}[/red]")
        return

    console.print("[green]✓ 连接成功[/green]")

    # 保存
    config.llm = LLMConfig(provider=provider, base_url=base_url, model=model)
    config_manager.set_api_key(provider, api_key)
    config_manager.save(config)

    console.print("[green]✓ AI 配置已更新[/green]")


def _config_output():
    """修改输出方式"""
    config = config_manager.load()

    console.print("\n选择默认输出方式:")
    console.print("  [1] 剪辑到本地（烧录字幕）")
    console.print("  [2] 推送到剪映")

    choice = Prompt.ask("请选择", choices=["1", "2"], default="1")
    config.output_mode = "local" if choice == "1" else "jianying"
    config_manager.save(config)

    console.print(f"[green]✓ 默认输出已更新为：{'本地' if config.output_mode == 'local' else '剪映'}[/green]")
