"""
Videocut CLI 入口

命令行界面，使用 Click 框架
"""

import click
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .config import config_manager

# Rich 控制台用于美化输出
console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="videocut")
def main():
    """
    Videocut - 智能口播视频剪辑工具

    自动识别口误，一键生成精剪视频
    """
    pass


@main.command()
def init():
    """首次配置（License、AI服务、输出方式）"""
    from .commands.init_cmd import run_init
    run_init()


@main.command()
@click.argument("video", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Choice(["local", "jianying"]),
    help="输出方式（默认使用配置）"
)
@click.option(
    "--skip-ai",
    is_flag=True,
    help="跳过 AI 文案重组"
)
def cut(video: str, output: str, skip_ai: bool):
    """
    剪辑视频

    VIDEO: 视频文件路径
    """
    # 检查是否已初始化
    if not config_manager.is_initialized():
        console.print("[red]错误：请先运行 videocut init 完成初始化[/red]")
        raise SystemExit(1)

    from .commands.cut_cmd import run_cut
    run_cut(video, output, skip_ai)


@main.command()
def config():
    """修改配置"""
    if not config_manager.is_initialized():
        console.print("[red]错误：请先运行 videocut init 完成初始化[/red]")
        raise SystemExit(1)

    from .commands.config_cmd import run_config
    run_config()


@main.command()
def status():
    """查看 License 和配置状态"""
    if not config_manager.is_initialized():
        console.print("[yellow]尚未初始化，请运行 videocut init[/yellow]")
        raise SystemExit(1)

    from .commands.status_cmd import run_status
    run_status()


if __name__ == "__main__":
    main()
