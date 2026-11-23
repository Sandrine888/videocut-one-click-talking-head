"""
cut 命令实现

视频剪辑主流程：转录 → AI重组(可选) → 口误识别 → 确认 → 剪辑 → 输出
"""

import os
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm, Prompt

console = Console()


def remap_transcript_for_cut(transcript, tasks):
    """把字符时间戳从原始时间轴映射到剪辑后时间轴。

    剪辑会删掉若干区间，若直接用原始转录结果生成 SRT，字幕会随时间越来越错位。
    此函数复用 editor.calculate_keep_segments 的合并逻辑，保证与视频剪辑一致。
    """
    from ..editor import calculate_keep_segments
    from ..transcribe import TranscriptResult, CharTimestamp

    keeps = calculate_keep_segments(tasks, transcript.duration)
    mapped: list = []
    new_pos = 0.0

    for seg in keeps:
        offset = seg.start - new_pos
        for char in transcript.chars:
            if seg.start <= char.start < seg.end:
                start = round(char.start - offset, 3)
                end = round(min(char.end, seg.end) - offset, 3)
                if end > start:
                    mapped.append(CharTimestamp(char.char, start, end))
        new_pos += seg.end - seg.start

    return TranscriptResult(
        video_file=transcript.video_file,
        full_text="".join(c.char for c in mapped),
        duration=round(new_pos, 3),
        chars=mapped,
    )


def run_cut(video: str, output: str = None, skip_ai: bool = False):
    """
    运行剪辑流程

    Args:
        video: 视频文件路径
        output: 输出方式 (local/jianying)
        skip_ai: 是否跳过 AI 文案重组
    """
    from ..config import config_manager
    from ..transcribe import transcribe_with_cache
    from ..slip_detect import detect_all, SlipDetectResult
    from ..editor import cut_video, get_output_path
    from ..output.local import generate_srt, burn_subtitles
    from ..output.jianying import push_to_jianying, check_jianying_installed

    # 检查文件存在
    if not os.path.exists(video):
        console.print(f"[red]错误: 文件不存在 - {video}[/red]")
        return

    config = config_manager.load()

    # 使用默认输出方式
    if output is None:
        output = config.output_mode

    # 检查剪映是否安装（如果选择剪映输出）
    if output == "jianying" and not check_jianying_installed():
        console.print("[yellow]警告: 未检测到剪映，将使用本地输出[/yellow]")
        output = "local"

    total_steps = 5 if not skip_ai else 4
    step = 0

    console.print(f"\n[bold]{'='*50}[/bold]")
    console.print(f"[bold]开始处理: {Path(video).name}[/bold]")
    console.print(f"[dim]输出方式: {'本地' if output == 'local' else '剪映'}[/dim]")
    console.print(f"[bold]{'='*50}[/bold]\n")

    # ==================== 步骤1: 转录 ====================
    step += 1
    console.print(f"[cyan][{step}/{total_steps}] 转录视频...[/cyan]")
    try:
        transcript = transcribe_with_cache(video)
        console.print(f"   转录文本: {transcript.full_text[:50]}...")
        console.print(f"   共 {len(transcript.chars)} 字\n")
    except Exception as e:
        console.print(f"[red]转录失败: {e}[/red]")
        return

    # ==================== 步骤2: AI 文案重组（可选）====================
    ai_tasks = []
    if not skip_ai:
        step += 1
        console.print(f"[cyan][{step}/{total_steps}] AI 文案分析...[/cyan]")

        try:
            from ..ai_rewrite import analyze_transcript, display_rewrite_plans, convert_plan_to_tasks

            result = analyze_transcript(transcript)

            if result and result.plans:
                display_rewrite_plans(result)

                # 让用户选择方案
                console.print("\n[yellow]请选择优化方案[/yellow]")
                choices = [str(i+1) for i in range(len(result.plans))] + ["0"]
                choice = Prompt.ask(
                    f"输入 1-{len(result.plans)} 选择方案，0 跳过",
                    choices=choices,
                    default="0"
                )

                if choice != "0":
                    selected_plan = result.plans[int(choice) - 1]
                    ai_tasks = convert_plan_to_tasks(selected_plan, transcript)
                    console.print(f"[green]已选择: {selected_plan.name}[/green]")
                else:
                    console.print("[dim]跳过 AI 优化[/dim]")
            else:
                console.print("[yellow]AI 分析未返回有效结果，跳过[/yellow]")

        except Exception as e:
            console.print(f"[yellow]AI 分析跳过: {e}[/yellow]")

        console.print()

    # ==================== 步骤3: 口误识别 ====================
    step += 1
    console.print(f"[cyan][{step}/{total_steps}] 识别口误...[/cyan]")
    try:
        detect_result = detect_all(transcript)
        detect_result.print_summary()
        console.print()
    except Exception as e:
        console.print(f"[red]口误识别失败: {e}[/red]")
        return

    # 合并 AI 建议的删除任务
    if ai_tasks:
        detect_result.slips.extend(ai_tasks)
        console.print(f"[dim]已合并 AI 建议的 {len(ai_tasks)} 处删除[/dim]\n")

    # 如果没有检测到任何问题
    if not detect_result.all_tasks:
        console.print("[green]没有检测到需要处理的内容[/green]")
        console.print("视频无需剪辑，处理完成。")
        return

    # ==================== 步骤4: 确认删除任务 ====================
    step += 1
    console.print(f"[cyan][{step}/{total_steps}] 确认删除任务...[/cyan]\n")

    # 显示删除任务
    print_delete_tasks(detect_result)

    # 用户确认
    console.print("\n[yellow]请确认以上删除任务[/yellow]")
    console.print("输入 [bold]y[/bold] 确认全部, [bold]n[/bold] 取消, [bold]e[/bold] 编辑")

    choice = Prompt.ask("选择", choices=["y", "n", "e"], default="y")

    if choice == "n":
        console.print("[yellow]已取消操作[/yellow]")
        return
    elif choice == "e":
        detect_result = edit_delete_tasks(detect_result)
        if not detect_result.confirmed_tasks:
            console.print("[yellow]没有确认的删除任务，操作取消[/yellow]")
            return

    # ==================== 步骤5: 执行剪辑 ====================
    step += 1
    console.print(f"\n[cyan][{step}/{total_steps}] 执行剪辑...[/cyan]")

    # 生成输出路径
    cut_output = get_output_path(video, "_cut")

    # 执行剪辑
    confirmed_tasks = detect_result.confirmed_tasks
    success = cut_video(
        video,
        cut_output,
        confirmed_tasks,
        transcript.duration
    )

    if not success:
        console.print("[red]剪辑失败[/red]")
        return

    # 字幕必须按剪辑后的时间轴生成，否则会越来越错位
    cut_transcript = remap_transcript_for_cut(transcript, confirmed_tasks)

    # ==================== 输出处理 ====================
    if output == "local":
        console.print("\n[cyan]生成本地输出...[/cyan]")

        # 生成字幕
        srt_path = str(Path(cut_output).with_suffix(".srt"))
        generate_srt(cut_transcript, srt_path)

        # 询问是否烧录字幕
        if Confirm.ask("是否将字幕烧录到视频中?", default=True):
            final_output = get_output_path(video, "_final")
            burn_subtitles(cut_output, srt_path, final_output)
            console.print(f"\n[green bold]✓ 处理完成！[/green bold]")
            console.print(f"   最终视频: {final_output}")
        else:
            console.print(f"\n[green bold]✓ 处理完成！[/green bold]")
            console.print(f"   剪辑视频: {cut_output}")
            console.print(f"   字幕文件: {srt_path}")

    elif output == "jianying":
        console.print("\n[cyan]推送到剪映...[/cyan]")

        # 生成字幕（剪映可以导入）
        srt_path = str(Path(cut_output).with_suffix(".srt"))
        generate_srt(cut_transcript, srt_path)

        # 推送到剪映
        success = push_to_jianying(cut_output)

        if success:
            console.print(f"\n[green bold]✓ 处理完成！[/green bold]")
            console.print(f"   剪辑视频已推送到剪映草稿箱")
            console.print(f"   字幕文件: {srt_path}")
        else:
            console.print(f"\n[yellow]剪映推送失败，视频已保存到本地[/yellow]")
            console.print(f"   剪辑视频: {cut_output}")

    console.print()


def print_delete_tasks(result: 'SlipDetectResult'):
    """打印删除任务列表"""
    from ..slip_detect import SlipType

    # 口误
    if result.slips:
        table = Table(title=f"口误 ({len(result.slips)}处)", show_header=True)
        table.add_column("序号", style="dim", width=4)
        table.add_column("时间", width=16)
        table.add_column("类型", width=8)
        table.add_column("删除", style="red")
        table.add_column("保留", style="green")

        for i, task in enumerate(result.slips, 1):
            table.add_row(
                str(i),
                f"{task.start:.2f}-{task.end:.2f}",
                task.slip_type.value,
                task.text,
                task.keep_text
            )
        console.print(table)
        console.print()

    # 语气词
    if result.fillers:
        table = Table(title=f"语气词 ({len(result.fillers)}处)", show_header=True)
        table.add_column("序号", style="dim", width=4)
        table.add_column("时间", width=16)
        table.add_column("删除", style="red")
        table.add_column("上下文")

        for i, task in enumerate(result.fillers, 1):
            table.add_row(
                str(i),
                f"{task.start:.2f}-{task.end:.2f}",
                task.text,
                task.context
            )
        console.print(table)
        console.print()

    # 静音
    if result.silences:
        table = Table(title=f"静音 ({len(result.silences)}处)", show_header=True)
        table.add_column("序号", style="dim", width=4)
        table.add_column("时间", width=16)
        table.add_column("时长", width=8)
        table.add_column("上下文")

        for i, task in enumerate(result.silences, 1):
            table.add_row(
                str(i),
                f"{task.start:.2f}-{task.end:.2f}",
                f"{task.duration:.1f}s",
                task.context
            )
        console.print(table)


def edit_delete_tasks(result: 'SlipDetectResult') -> 'SlipDetectResult':
    """
    交互式编辑删除任务

    允许用户取消某些任务
    """
    console.print("\n[bold]编辑删除任务[/bold]")
    console.print("输入要取消的任务编号（用逗号分隔），直接回车保留全部\n")

    all_tasks = result.all_tasks
    total = len(all_tasks)

    # 显示所有任务
    for i, task in enumerate(all_tasks, 1):
        status = "✓" if task.confirmed else "✗"
        if task.text:
            desc = f"删除 \"{task.text}\""
        else:
            desc = f"删除静音 {task.duration:.1f}s"
        console.print(f"  [{status}] {i}. ({task.start:.2f}-{task.end:.2f}) {desc}")

    console.print()
    cancel_input = Prompt.ask("取消任务编号", default="")

    if cancel_input.strip():
        try:
            cancel_indices = [int(x.strip()) for x in cancel_input.split(",")]
            for idx in cancel_indices:
                if 1 <= idx <= total:
                    all_tasks[idx - 1].confirmed = False
                    console.print(f"  已取消任务 {idx}")
        except ValueError:
            console.print("[yellow]输入格式错误，保留全部任务[/yellow]")

    confirmed_count = len([t for t in all_tasks if t.confirmed])
    console.print(f"\n确认 {confirmed_count}/{total} 个任务")

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_cut(sys.argv[1])
    else:
        print("用法: python -m videocut.commands.cut_cmd <video_path>")
