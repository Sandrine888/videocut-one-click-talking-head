"""
语音转录模块

使用 FunASR 实现 30s 分段转录，获取字符级时间戳
"""

import os
import json
import subprocess
import hashlib
import importlib.metadata
import tempfile
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _load_model(model_name: str):
    from funasr import AutoModel
    return AutoModel(model=model_name, disable_update=True)


def transcribe_video(video_path: str, segment_length: int = 30,
                     model_name: str = "paraformer-zh", on_progress=None) -> TranscriptResult:
    """
    转录视频

    使用 30s 分段策略避免时间戳漂移

    Args:
        video_path: 视频文件路径
        segment_length: 分段长度（秒），默认 30

    Returns:
        TranscriptResult 转录结果
    """
    # 获取视频时长
    duration = get_video_duration(video_path)
    console.print(f"视频时长: {duration:.1f}秒")

    # 加载模型
    console.print("⏳ 加载语音识别模型...")
    model = _load_model(model_name)

    # 计算分段
    import math
    if segment_length <= 0:
        raise ValueError("识别分段长度必须大于零。")
    num_segments = math.ceil(duration / segment_length)
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
            temp_dir = tempfile.TemporaryDirectory(prefix="videocut_audio_")
            wav_path = str(Path(temp_dir.name) / f"segment_{i}.wav")

            # FunASR 转录
            try:
                extract_audio_segment(video_path, start, seg_duration, wav_path)
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
                temp_dir.cleanup()

            progress.update(task, advance=1)
            if on_progress:
                on_progress((i + 1) / num_segments)

    # 构建完整文本
    full_text = "".join(c.char for c in all_chars)

    console.print(f"[green]✓ 转录完成，共 {len(full_text)} 字[/green]")

    return TranscriptResult(
        video_file=video_path,
        full_text=full_text,
        duration=duration,
        chars=all_chars
    )


def source_digest(video_path):
    digest = hashlib.sha256()
    with open(video_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_model_name(model):
    if model == "paraformer-zh":
        # Known default FunASR alias: use already downloaded weights directly,
        # avoiding a hub metadata request on every local run.
        cache_root = Path(os.environ.get("MODELSCOPE_CACHE", str(Path.home() / ".cache" / "modelscope")))
        name = "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        for candidate in (Path(__file__).resolve().parent.parent / "models" / model, cache_root / "models" / ("iic--" + name) / "snapshots" / "master",
                          cache_root / "hub" / "models" / "iic" / name,
                          cache_root / "hub" / "iic" / name):
            if (candidate / "model.pt").is_file() and (candidate / "config.yaml").is_file():
                return str(candidate.resolve())
    return model


def recognition_config(config=None):
    config = dict(config or {})
    if set(config) - {"model_name", "segment_length", "model_revision"}:
        raise ValueError("存在不支持的语音识别配置。")
    # A local model directory identifies its actual weights as well as its name.
    model = resolve_model_name(str(config.get("model_name", "paraformer-zh")))
    model_path = Path(model)
    local_version = None
    if model_path.is_dir():
        weights = model_path / "model.pt"
        if weights.exists():
            stat = weights.stat()
            local_version = [stat.st_size, stat.st_mtime_ns]
    try:
        version = importlib.metadata.version("funasr")
    except importlib.metadata.PackageNotFoundError:
        version = "unavailable"
    # Revision is metadata for cache invalidation, passed to supported backends
    # by the adapter; the current backend supports only its installed default.
    if config.get("model_revision"):
        raise ValueError("当前 FunASR 适配器暂不支持指定模型版本。")
    return {"backend": "funasr", "model_name": model,
            "segment_length": int(config.get("segment_length", 30)),
            "funasr_version": version, "local_weights": local_version,
            "adapter_version": 2}


def validate_transcript(transcript):
    import math
    if not math.isfinite(transcript.duration) or transcript.duration <= 0:
        raise ValueError("识别结果时长无效。")
    previous = -1.0
    for char in transcript.chars:
        if (not char.char or not math.isfinite(char.start) or not math.isfinite(char.end)
                or char.start < 0 or char.end <= char.start
                or char.start < previous or char.end > transcript.duration + 0.05):
            raise ValueError("识别结果包含无效的逐字时间戳。")
        previous = char.start
    if transcript.full_text != "".join(c.char for c in transcript.chars):
        raise ValueError("识别文本与逐字结果不一致。")


def transcribe_with_cache(video_path: str, *, cache_dir=None, config=None,
                          on_event=None, recognizer=None, local_only=False) -> TranscriptResult:
    """Content/config-addressed cache. Unverified legacy JSON is never trusted."""
    video_path = Path(video_path).resolve()
    settings = recognition_config(config)
    if settings["segment_length"] <= 0:
        raise ValueError("识别分段长度必须大于零。")
    source_hash = source_digest(video_path)
    config_hash = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    directory = Path(cache_dir) if cache_dir else video_path.parent / ".videocut-cache"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{source_hash}_{config_hash}.transcript.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if (data["schema_version"] != 2 or data["source_sha256"] != source_hash
                    or data["configuration"] != settings or data["complete"] is not True):
                raise ValueError("缓存身份不匹配")
            raw = data["transcript"]
            result = TranscriptResult(str(video_path), raw["full_text"],
                                      raw["duration"], [CharTimestamp(**c) for c in raw["chars"]])
            validate_transcript(result)
            if on_event:
                on_event("cache_hit", str(json_path))
            return result
        except (ValueError, KeyError, TypeError, OSError):
            if on_event:
                on_event("cache_invalid", str(json_path))
    if on_event:
        on_event("recognizing", "正在识别语音，首次准备模型可能需要较长时间。")
    if local_only:
        path = Path(settings['model_name'])
        if not ((path / 'config.yaml').is_file() and (path / 'model.pt').is_file()):
            raise ValueError('本地识别模型尚未准备好。请将完整模型目录放入工具目录下的 models/paraformer-zh。')
    recognize = recognizer or transcribe_video
    result = recognize(str(video_path), segment_length=settings["segment_length"],
                       model_name=settings["model_name"])
    validate_transcript(result)
    payload = dict(schema_version=2, source_sha256=source_hash, configuration=settings,
                   complete=True, transcript=result.to_dict())
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     suffix=".tmp", delete=False) as temporary:
        temp_path = Path(temporary.name)
        json.dump(payload, temporary, ensure_ascii=False, indent=2)
    try:
        os.replace(temp_path, json_path)
    finally:
        temp_path.unlink(missing_ok=True)
    if on_event:
        on_event("cache_saved", str(json_path))
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
