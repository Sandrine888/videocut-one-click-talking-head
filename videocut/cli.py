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
@click.argument("video", type=click.Path(exists=True, dir_okay=False))
@click.option("--output-dir", default="results", show_default=True, type=click.Path(file_okay=False))
@click.option("--trim-silence", is_flag=True, help="仅删除经音频检测的长停顿，默认不删。")
@click.option("--template", type=click.Path(exists=True, dir_okay=False))
@click.option("--adapters", help="团队适配器 模块名:工厂函数")
@click.option("--model-name", default="paraformer-zh", show_default=True)
@click.option("--mode", type=click.Choice(["quick", "advanced"]), default="quick", show_default=True)
@click.option("--auto-apply", is_flag=True, help="在进阶模式中自动应用可定位的删减建议。")
def generate(video, output_dir, trim_silence, template, adapters, model_name, mode, auto_apply):
    """一次生成字幕成片，全程不询问。"""
    from .commands.generate_cmd import run_generate
    from .pipeline import GenerationError
    try:
        run_generate(video, output_dir, trim_silence, template, adapters, model_name, mode, auto_apply)
    except GenerationError as exc:
        raise click.ClickException(f"{exc.stage}失败：{exc}；详细日志：{exc.task_dir}") from exc


@main.command()
@click.option("--port", default=8765, type=click.IntRange(0, 65535), show_default=True)
@click.option("--no-browser", is_flag=True)
@click.option("--workspace", default=".videocut-work", show_default=True, type=click.Path(file_okay=False))
@click.option("--adapters", help="团队适配器 模块名:工厂函数")
def serve(port, no_browser, workspace, adapters):
    """打开本机网页入口。关闭服务窗口后停止服务。"""
    from .web import serve as run_server
    run_server(port=port, open_browser=not no_browser, workspace=workspace, adapters_spec=adapters)


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
