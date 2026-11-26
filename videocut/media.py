"""Media inspection and checked subprocesses shared by the noninteractive pipeline."""

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess


class MediaError(RuntimeError):
    pass


def run_process(args, *, timeout=3600, cwd=None):
    result = subprocess.run(
        [str(a) for a in args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise MediaError(result.stderr[-4000:] or f"程序退出码 {result.returncode}")
    return result


def tool(name):
    executable = shutil.which(name)
    if not executable:
        raise MediaError(f"缺少 {name}，请安装 FFmpeg 并重新打开工具。")
    return executable


def check_tools():
    filters = run_process([tool("ffmpeg"), "-hide_banner", "-filters"], timeout=30).stdout
    encoders = run_process([tool("ffmpeg"), "-hide_banner", "-encoders"], timeout=30).stdout
    tool("ffprobe")
    if not re.search(r"\bsubtitles\b", filters):
        raise MediaError("FFmpeg 缺少字幕渲染功能，请使用包含 libass 的版本。")
    if not re.search(r"\blibx264\b", encoders) or not re.search(r"\baac\b", encoders):
        raise MediaError("FFmpeg 缺少 H.264 或 AAC 编码器。")


def inspect_media(path, *, require_audio=True):
    path = Path(path).resolve()
    if not path.is_file():
        raise MediaError("找不到视频文件，请重新选择。")
    if not path.stat().st_size:
        raise MediaError("文件是空的，请选择有效视频。")
    try:
        raw = json.loads(run_process([
            tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
            "-of", "json", path,
        ], timeout=60).stdout)
    except (MediaError, ValueError) as exc:
        raise MediaError("无法读取视频，文件可能损坏或编码不受支持。请换一段原片重试。") from exc
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video:
        raise MediaError("文件不包含可用的视频画面。")
    if require_audio and not audio:
        raise MediaError("视频没有音轨，当前版本需要带口播原声的视频。")
    duration = float(raw.get("format", {}).get("duration") or video.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("无法读取有效的视频时长。")
    width, height = int(video["width"]), int(video["height"])
    rotation = float(video.get("tags", {}).get("rotate", 0))
    for entry in video.get("side_data_list", []):
        if "rotation" in entry:
            rotation = float(entry["rotation"])
    if round(rotation) % 180:
        width, height = height, width
    num, _, den = video.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    return dict(path=str(path), duration=duration, width=width, height=height,
                rotation=rotation, direction="竖屏" if height > width else "横屏",
                fps=fps, video_codec=video.get("codec_name"),
                audio_codec=audio.get("codec_name") if audio else None)


def render_video(input_path, subtitle_asset, output_path):
    # Use a short relative asset name and a private cwd: Windows drive letters,
    # apostrophes and Unicode input paths never become FFmpeg filter syntax.
    subtitle_asset = Path(subtitle_asset).resolve()
    workdir = subtitle_asset.parent
    suffix = subtitle_asset.suffix.lower()
    safe_asset = workdir / ("render_subtitles" + suffix)
    if subtitle_asset != safe_asset:
        shutil.copyfile(subtitle_asset, safe_asset)
    filter_arg = f"subtitles=filename={safe_asset.name}"
    input_media = inspect_media(input_path)
    audio_options = (["-c:a", "copy"] if input_media["audio_codec"] == "aac" else
                     ["-c:a", "aac", "-b:a", "192k", "-t", str(input_media["duration"])])
    run_process([
        tool("ffmpeg"), "-hide_banner", "-y", "-i", Path(input_path).resolve(),
        "-map", "0:v:0", "-map", "0:a:0", "-vf", filter_arg,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", *audio_options,
        "-metadata:s:v:0", "rotate=0", "-movflags", "+faststart",
        Path(output_path).resolve(),
    ], cwd=workdir)


def verified_silences(video, duration, *, threshold=1.8, padding=0.25):
    """Conservative audio-energy gate; never infer silence from ASR text gaps."""
    if threshold < 0.5 or padding < 0.1 or padding * 2 >= threshold:
        raise ValueError("停顿参数无效。")
    result = run_process([
        tool("ffmpeg"), "-hide_banner", "-i", video, "-vn",
        "-af", f"silencedetect=noise=-45dB:d={threshold}", "-f", "null", "-",
    ])
    ranges, start = [], None
    for line in result.stderr.splitlines():
        found = re.search(r"silence_start: ([0-9.eE+\-]+)", line)
        if found:
            start = max(0.0, float(found.group(1)))
        found = re.search(r"silence_end: ([0-9.eE+\-]+)", line)
        if found and start is not None:
            end = min(duration, float(found.group(1)))
            if end - start >= threshold:
                ranges.append((round(start + padding, 3), round(end - padding, 3)))
            start = None
    if start is not None and duration - start >= threshold:
        ranges.append((round(start + padding, 3), round(duration - padding, 3)))
    return [(s, e) for s, e in ranges if e > s]
