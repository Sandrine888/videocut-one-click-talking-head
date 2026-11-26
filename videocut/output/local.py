"""
本地输出模块

生成 SRT 字幕文件并烧录到视频
"""

import subprocess
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from rich.console import Console

from ..transcribe import TranscriptResult, CharTimestamp

console = Console()


@dataclass
class SubtitleSegment:
    """字幕片段"""
    index: int
    start: float  # 秒
    end: float    # 秒
    text: str


def format_srt_time(seconds: float) -> str:
    """
    将秒数转换为 SRT 时间格式

    Args:
        seconds: 时间（秒）

    Returns:
        SRT 时间格式 "HH:MM:SS,mmm"
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def create_subtitle_segments(
    chars: List[CharTimestamp],
    max_chars: int = 15,
    max_duration: float = 3.0
) -> List[SubtitleSegment]:
    """
    将字符级时间戳转换为字幕片段

    Args:
        chars: 字符时间戳列表
        max_chars: 每行最大字符数
        max_duration: 每行最大时长（秒）

    Returns:
        字幕片段列表
    """
    if not chars:
        return []

    segments: List[SubtitleSegment] = []
    current_chars: List[CharTimestamp] = []
    index = 1

    for char in chars:
        current_chars.append(char)

        # 判断是否需要换行
        should_break = False

        # 字数达到上限
        if len(current_chars) >= max_chars:
            should_break = True

        # 时长达到上限
        if current_chars and (char.end - current_chars[0].start) >= max_duration:
            should_break = True

        # 遇到标点符号
        if char.char in '。！？，、；：':
            should_break = True

        if should_break and current_chars:
            text = "".join(c.char for c in current_chars)
            segments.append(SubtitleSegment(
                index=index,
                start=current_chars[0].start,
                end=current_chars[-1].end,
                text=text
            ))
            index += 1
            current_chars = []

    # 处理剩余字符
    if current_chars:
        text = "".join(c.char for c in current_chars)
        segments.append(SubtitleSegment(
            index=index,
            start=current_chars[0].start,
            end=current_chars[-1].end,
            text=text
        ))

    return segments


def generate_srt(
    transcript: TranscriptResult,
    output_path: str,
    max_chars: int = 15,
    max_duration: float = 3.0
) -> str:
    """
    生成 SRT 字幕文件

    Args:
        transcript: 转录结果
        output_path: 输出路径
        max_chars: 每行最大字符数
        max_duration: 每行最大时长

    Returns:
        SRT 文件路径
    """
    segments = create_subtitle_segments(
        transcript.chars,
        max_chars=max_chars,
        max_duration=max_duration
    )

    srt_content = []
    for seg in segments:
        srt_content.append(str(seg.index))
        srt_content.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        srt_content.append(seg.text)
        srt_content.append("")  # 空行分隔

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_content))

    console.print(f"[green]✓ 字幕已生成: {output_path}[/green]")
    console.print(f"  共 {len(segments)} 条字幕")

    return output_path


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 24,
    font_color: str = "white",
    outline_color: str = "black",
    outline_width: int = 2,
    position: str = "bottom"
) -> bool:
    """
    将字幕烧录到视频

    Args:
        video_path: 输入视频路径
        srt_path: SRT 字幕路径
        output_path: 输出视频路径
        font_size: 字体大小
        font_color: 字体颜色
        outline_color: 描边颜色
        outline_width: 描边宽度
        position: 字幕位置 (bottom/center/top)

    Returns:
        是否成功
    """
    console.print("⏳ 正在烧录字幕...")

    # 计算垂直位置
    if position == "bottom":
        margin_v = 50
    elif position == "center":
        margin_v = 0  # 会在 filter 中调整
    else:  # top
        margin_v = 50

    # 构建 subtitles filter
    # 需要对路径中的特殊字符进行转义
    escaped_srt = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    subtitle_filter = (
        f"subtitles='{escaped_srt}':"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour=&H00FFFFFF,"  # 白色
        f"OutlineColour=&H00000000,"  # 黑色描边
        f"Outline={outline_width},"
        f"MarginV={margin_v},"
        f"Alignment=2'"  # 底部居中
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "copy",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            console.print(f"[red]FFmpeg 错误:[/red]")
            console.print(result.stderr[-500:])
            return False

        output_size = Path(output_path).stat().st_size / (1024 * 1024)
        console.print(f"[green]✓ 字幕烧录完成[/green]")
        console.print(f"   输出: {output_path}")
        console.print(f"   大小: {output_size:.1f}MB")

        return True

    except FileNotFoundError:
        console.print("[red]错误: FFmpeg 未安装[/red]")
        return False

    except Exception as e:
        console.print(f"[red]烧录失败: {e}[/red]")
        return False


def process_local_output(
    video_path: str,
    transcript: TranscriptResult,
    output_dir: Optional[str] = None,
    burn_subs: bool = True
) -> dict:
    """
    完整的本地输出流程

    Args:
        video_path: 输入视频路径（已剪辑）
        transcript: 转录结果（已剪辑后的）
        output_dir: 输出目录，默认与输入同目录
        burn_subs: 是否烧录字幕

    Returns:
        {"video": 输出视频路径, "srt": SRT路径}
    """
    video_path = Path(video_path)

    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = video_path.parent

    # 生成文件名
    base_name = video_path.stem
    srt_path = out_dir / f"{base_name}.srt"
    final_video_path = out_dir / f"{base_name}_final{video_path.suffix}"

    # 生成 SRT
    generate_srt(transcript, str(srt_path))

    result = {
        "srt": str(srt_path),
        "video": str(video_path)
    }

    # 烧录字幕
    if burn_subs:
        success = burn_subtitles(
            str(video_path),
            str(srt_path),
            str(final_video_path)
        )
        if success:
            result["video"] = str(final_video_path)

    return result


if __name__ == "__main__":
    # 测试
    test_chars = [
        CharTimestamp("你", 1.0, 1.2),
        CharTimestamp("好", 1.2, 1.4),
        CharTimestamp("我", 1.5, 1.7),
        CharTimestamp("是", 1.7, 1.9),
        CharTimestamp("测", 2.0, 2.2),
        CharTimestamp("试", 2.2, 2.4),
        CharTimestamp("。", 2.4, 2.5),
        CharTimestamp("这", 3.0, 3.2),
        CharTimestamp("是", 3.2, 3.4),
        CharTimestamp("第", 3.4, 3.6),
        CharTimestamp("二", 3.6, 3.8),
        CharTimestamp("句", 3.8, 4.0),
        CharTimestamp("话", 4.0, 4.2),
        CharTimestamp("。", 4.2, 4.3),
    ]

    segments = create_subtitle_segments(test_chars)
    print("字幕片段:")
    for seg in segments:
        print(f"  {seg.index}: {format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        print(f"     {seg.text}")
