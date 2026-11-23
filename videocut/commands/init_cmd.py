"""
init 命令实现

交互式初始化配置
"""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from ..config import config_manager, Config, LLMConfig

console = Console()


def run_init():
    """运行初始化流程"""
    console.print(Panel.fit(
        "[bold blue]欢迎使用 Videocut 口播视频剪辑工具！[/bold blue]\n"
        "让我们完成首次配置",
        title="Videocut"
    ))

    config = config_manager.load()

    # 第1步：License 验证
    console.print("\n[bold]第1步：License 验证[/bold]")
    license_key = Prompt.ask("请输入 License Key")

    # TODO: 实际验证 License
    from ..license import verify_license
    result = verify_license(license_key)

    if not result["valid"]:
        console.print(f"[red]验证失败：{result.get('error', '未知错误')}[/red]")
        if Confirm.ask("是否重新输入？"):
            return run_init()
        return

    config.license_key = license_key
    console.print(f"[green]✓ License 验证成功，有效期至 {result.get('expires_at', '未知')}[/green]")

    # 第2步：配置 AI 服务
    console.print("\n[bold]第2步：配置 AI 服务（用于文案重组）[/bold]")
    console.print("选择 LLM 提供商:")
    console.print("  [1] OpenAI")
    console.print("  [2] Anthropic (Claude)")
    console.print("  [3] OpenAI 兼容服务（DeepSeek/Moonshot/硅基流动等）")

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
    test_result = test_llm_connection(provider, api_key, model, base_url)

    if not test_result["success"]:
        console.print(f"[red]✗ 连接失败：{test_result.get('error', '未知错误')}[/red]")
        if Confirm.ask("是否重新配置 AI 服务？"):
            return run_init()
        return

    console.print("[green]✓ 连接成功，模型响应正常[/green]")

    # 保存 LLM 配置
    config.llm = LLMConfig(provider=provider, base_url=base_url, model=model)
    config_manager.set_api_key(provider, api_key)

    # 第3步：选择输出方式
    console.print("\n[bold]第3步：选择默认输出方式[/bold]")
    console.print("  [1] 剪辑到本地（烧录字幕，直接分享）")
    console.print("  [2] 推送到剪映（在剪映中加字幕）")

    output_choice = Prompt.ask("请选择", choices=["1", "2"], default="1")
    config.output_mode = "local" if output_choice == "1" else "jianying"
    console.print(f"[green]✓ 默认输出：{'本地' if config.output_mode == 'local' else '剪映'}[/green]")

    # 第4步：检测依赖
    console.print("\n[bold]第4步：检测依赖[/bold]")
    _check_dependencies()

    # 保存配置
    config_manager.save(config)

    console.print("\n" + "="*50)
    console.print("[bold green]配置完成！[/bold green]")
    console.print("运行 [cyan]videocut cut video.mp4[/cyan] 开始剪辑")


def _check_dependencies():
    """检测必要依赖"""
    import shutil
    import sys

    # 检测 FFmpeg
    if shutil.which("ffmpeg"):
        console.print("[green]✓ FFmpeg 已安装[/green]")
    else:
        console.print("[red]✗ FFmpeg 未安装[/red]")
        console.print("  请安装: brew install ffmpeg (macOS) 或 choco install ffmpeg (Windows)")

    # 检测 Python 版本
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    console.print(f"[green]✓ Python {py_version}[/green]")

    # 检测语音识别模型（首次会下载）
    console.print("⏳ 检测语音识别模型...")
    try:
        # 只检测，不实际加载
        from funasr import AutoModel
        console.print("[green]✓ 语音识别模型就绪[/green]")
    except ImportError:
        console.print("[yellow]⚠ 语音识别模块未安装，首次使用时将自动下载模型（约2GB）[/yellow]")
