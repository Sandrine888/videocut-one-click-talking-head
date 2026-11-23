"""
语音转录模块

使用 FunASR 实现 30s 分段转录，获取字符级时间戳
"""

import os
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()


@dataclass
class CharTimestamp:
    """字符时间戳"""
    char: str
    start: float  # 秒
    end: float    # 秒


@dataclass
class TranscriptResult:
    """转录结果"""
    video_file: str
    full_text: str
    duration: float  # 秒
    chars: List[CharTimestamp]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_file": self.video_file,
            "full_text": self.full_text,
            "duration": self.duration,
            "chars": [asdict(c) for c in self.chars]
        }

    def save(self, output_path: str):
        """保存为 JSON"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, json_path: str) -> "TranscriptResult":
        """从 JSON 加载"""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chars = [CharTimestamp(**c) for c in data["chars"]]
        return cls(
            video_file=data["video_file"],
            full_text=data["full_text"],
            duration=data["duration"],
            chars=chars
        )


def get_video_duration(video_path: str) -> float:
    """
    获取视频时长（秒）
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def extract_audio_segment(video_path: str, start: float, duration: float, output_path: str):
    """
    提取视频片段的音频

    Args:
        video_path: 视频文件路径
        start: 起始时间（秒）
        duration: 时长（秒）
        output_path: 输出音频路径
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", str(start),
        "-t", str(duration),
        "-vn",  # 不要视频
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", "16000",  # 16kHz 采样率
        "-ac", "1",  # 单声道
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def transcribe_video(video_path: str, segment_length: int = 30) -> TranscriptResult:
    """
    转录视频

    使用 30s 分段策略避免时间戳漂移

    Args:
        video_path: 视频文件路径
        segment_length: 分段长度（秒），默认 30

    Returns:
        TranscriptResult 转录结果
    """
    from funasr import AutoModel

    # 获取视频时长
    duration = get_video_duration(video_path)
    console.print(f"视频时长: {duration:.1f}秒")

    # 加载模型
    console.print("⏳ 加载语音识别模型...")
    model = AutoModel(model="paraformer-zh", disable_update=True)

    # 计算分段
    num_segments = int(duration // segment_length) + 1
    all_chars: List[CharTimestamp] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("正在转录...", total=num_segments)

        for i in range(num_segments):
            start = i * segment_length
            seg_duration = min(segment_length, duration - start)

            if seg_duration <= 0:
                break

            # 提取音频段
            wav_path = f"/tmp/videocut_seg_{i}.wav"
            extract_audio_segment(video_path, start, seg_duration, wav_path)

            # FunASR 转录
            try:
                result = model.generate(
                    input=wav_path,
                    return_raw_text=True,
                    timestamp_granularity="character"
                )

                # 解析结果
                for item in result:
                    if "timestamp" in item and "text" in item:
                        text = item["text"].replace(" ", "")
                        timestamps = item["timestamp"]

                        for j, (char, ts) in enumerate(zip(text, timestamps)):
                            # 跳过标点符号（没有时间戳）
                            if j < len(timestamps):
                                all_chars.append(CharTimestamp(
                                    char=char,
                                    start=round(start + ts[0] / 1000, 3),  # 加上段偏移
                                    end=round(start + ts[1] / 1000, 3)
                                ))

            finally:
                # 清理临时文件
                if os.path.exists(wav_path):
                    os.remove(wav_path)

            progress.update(task, advance=1)

    # 构建完整文本
    full_text = "".join(c.char for c in all_chars)

    console.print(f"[green]✓ 转录完成，共 {len(full_text)} 字[/green]")

    return TranscriptResult(
        video_file=video_path,
        full_text=full_text,
        duration=duration,
        chars=all_chars
    )


def transcribe_with_cache(video_path: str) -> TranscriptResult:
    """
    带缓存的转录

    如果已有转录结果 JSON，直接加载
    """
    video_path = Path(video_path)
    json_path = video_path.with_suffix(".transcript.json")

    if json_path.exists():
        console.print(f"[cyan]发现已有转录结果，正在加载...[/cyan]")
        return TranscriptResult.load(str(json_path))

    # 执行转录
    result = transcribe_video(str(video_path))

    # 保存结果
    result.save(str(json_path))
    console.print(f"[dim]转录结果已保存: {json_path}[/dim]")

    return result


if __name__ == "__main__":
    # 测试
    import sys
    if len(sys.argv) > 1:
        video = sys.argv[1]
        result = transcribe_with_cache(video)
        print(f"\n完整文本:\n{result.full_text[:200]}...")
        print(f"\n前10个字符时间戳:")
        for c in result.chars[:10]:
            print(f"  {c.char}: {c.start:.2f}s - {c.end:.2f}s")
