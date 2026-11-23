"""
status 命令实现

查看状态
"""

from rich.console import Console
from rich.table import Table

from ..config import config_manager

console = Console()


def run_status():
    """显示 License 和配置状态"""
    config = config_manager.load()

    # License 状态
    console.print("\n[bold]License 状态[/bold]")
    table = Table(show_header=False, box=None)
    table.add_column("项目", style="cyan")
    table.add_column("值")

    table.add_row("License Key", _mask_key(config.license_key))
    table.add_row("状态", "[green]有效[/green]" if config.license_cache.valid else "[red]无效[/red]")
    table.add_row("到期时间", config.license_cache.expires_at or "未知")
    table.add_row("设备 ID", config.device_id[:16] + "...")

    console.print(table)

    # 配置状态
    console.print("\n[bold]配置状态[/bold]")
    table2 = Table(show_header=False, box=None)
    table2.add_column("项目", style="cyan")
    table2.add_column("值")

    table2.add_row("LLM 提供商", config.llm.provider)
    table2.add_row("LLM 模型", config.llm.model)
    if config.llm.base_url:
        table2.add_row("LLM Base URL", config.llm.base_url)
    table2.add_row("默认输出", "本地" if config.output_mode == "local" else "剪映")

    console.print(table2)


def _mask_key(key: str) -> str:
    """隐藏 key 中间部分"""
    if not key or len(key) < 8:
        return key or "未设置"
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
