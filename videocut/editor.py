"""
视频剪辑模块

根据删除任务执行 FFmpeg 剪辑
"""

import subprocess
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .slip_detect import DeleteTask

console = Console()


@dataclass
class KeepSegment:
    """保留片段"""
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def calculate_keep_segments(
    tasks: List[DeleteTask],
    video_duration: float
) -> List[KeepSegment]:
    """
    根据删除任务计算需要保留的时间段

    Args:
        tasks: 删除任务列表
        video_duration: 视频总时长

    Returns:
        保留片段列表
    """
    if not tasks:
        return [KeepSegment(0, video_duration)]

    # 按开始时间排序
    sorted_tasks = sorted(tasks, key=lambda t: t.start)

    # 合并重叠的删除区间
    delete_ranges: List[Tuple[float, float]] = []
    for task in sorted_tasks:
        if delete_ranges and task.start <= delete_ranges[-1][1]:
            # 合并重叠区间
            delete_ranges[-1] = (delete_ranges[-1][0], max(delete_ranges[-1][1], task.end))
        else:
            delete_ranges.append((task.start, task.end))

    # 计算保留区间
    keep_segments: List[KeepSegment] = []
    current_pos = 0.0

    for del_start, del_end in delete_ranges:
        if del_start > current_pos:
            keep_segments.append(KeepSegment(current_pos, del_start))
        current_pos = del_end

    # 添加最后一段
    if current_pos < video_duration:
        keep_segments.append(KeepSegment(current_pos, video_duration))

    return keep_segments


def generate_ffmpeg_filter(segments: List[KeepSegment]) -> str:
    """
    生成 FFmpeg filter_complex 脚本

    使用 trim + concat 方式实现无损剪辑

    Args:
        segments: 保留片段列表

    Returns:
        filter_complex 字符串
    """
    if not segments:
        return ""

    filter_parts = []
    concat_inputs = []

    for i, seg in enumerate(segments):
        # 视频 trim
        v_filter = f"[0:v]trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS[v{i}]"
        # 音频 trim
        a_filter = f"[0:a]atrim=start={seg.start:.3f}:end={seg.end:.3f},asetpts=PTS-STARTPTS[a{i}]"

        filter_parts.append(v_filter)
        filter_parts.append(a_filter)
        concat_inputs.append(f"[v{i}][a{i}]")

    # concat 合并
    concat_filter = f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[outv][outa]"
    filter_parts.append(concat_filter)

    return ";".join(filter_parts)


def cut_video(
    input_path: str,
    output_path: str,
    tasks: List[DeleteTask],
    video_duration: float
) -> bool:
    """
    执行视频剪辑

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        tasks: 删除任务列表
        video_duration: 视频总时长

    Returns:
        是否成功
    """
    # 只处理已确认的任务
    confirmed_tasks = [t for t in tasks if t.confirmed]

    if not confirmed_tasks:
        console.print("[yellow]没有需要删除的内容，跳过剪辑[/yellow]")
        # 直接复制原视频
        import shutil
        shutil.copy(input_path, output_path)
        return True

    console.print(f"⏳ 正在剪辑视频...")
    console.print(f"   删除 {len(confirmed_tasks)} 处内容")

    # 计算保留片段
    keep_segments = calculate_keep_segments(confirmed_tasks, video_duration)
    console.print(f"   保留 {len(keep_segments)} 个片段")

    # 计算删除的总时长
    total_delete = sum(t.duration for t in confirmed_tasks)
    console.print(f"   删除时长: {total_delete:.1f}s")

    # 生成 filter_complex
    filter_script = generate_ffmpeg_filter(keep_segments)

    # 构建 FFmpeg 命令
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_script,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",  # 高质量
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在剪辑...", total=None)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True, encoding="utf-8", errors="replace"
            )

            if result.returncode != 0:
                console.print(f"[red]FFmpeg 错误:[/red]")
                console.print(result.stderr[-500:])  # 只显示最后 500 字符
                return False

        # 获取输出文件大小
        output_size = Path(output_path).stat().st_size / (1024 * 1024)
        console.print(f"[green]✓ 剪辑完成[/green]")
        console.print(f"   输出: {output_path}")
        console.print(f"   大小: {output_size:.1f}MB")

        return True

    except FileNotFoundError:
        console.print("[red]错误: FFmpeg 未安装或不在 PATH 中[/red]")
        console.print("请安装 FFmpeg: https://ffmpeg.org/download.html")
        return False

    except Exception as e:
        console.print(f"[red]剪辑失败: {e}[/red]")
        return False


def get_output_path(input_path: str, suffix: str = "_cut") -> str:
    """
    生成输出文件路径

    Args:
        input_path: 输入文件路径
        suffix: 文件名后缀

    Returns:
        输出文件路径
    """
    path = Path(input_path)
    return str(path.parent / f"{path.stem}{suffix}{path.suffix}")


if __name__ == "__main__":
    # 测试
    from .slip_detect import SlipType

    test_tasks = [
        DeleteTask(SlipType.FILLER, 2.0, 2.5, "嗯", "你【嗯】好"),
        DeleteTask(SlipType.SILENCE, 5.0, 6.5, "", "静音"),
        DeleteTask(SlipType.STUTTER, 8.0, 8.5, "是", "我是是", keep_text="是"),
    ]

    segments = calculate_keep_segments(test_tasks, 10.0)
    print("保留片段:")
    for seg in segments:
        print(f"  {seg.start:.2f} - {seg.end:.2f} ({seg.duration:.2f}s)")

    filter_script = generate_ffmpeg_filter(segments)
    print(f"\nFFmpeg filter_complex:\n{filter_script}")
