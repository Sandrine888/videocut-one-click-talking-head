"""Actual FFmpeg export checks; ASR is isolated in separate real smoke runs."""
from pathlib import Path
import shutil

import pytest

from videocut import pipeline
from videocut.media import inspect_media, MediaError, run_process, tool, verified_silences
from videocut.transcribe import CharTimestamp, TranscriptResult

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="FFmpeg and FFprobe required")


@pytest.fixture
def real_video(tmp_path):
    path = tmp_path / "中文 口播's.mov"
    run_process([tool("ffmpeg"), "-hide_banner", "-y",
                 "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3",
                 "-c:v", "libx264", "-c:a", "pcm_s16le", path])
    return path


def fake_transcript(path, **kwargs):
    return TranscriptResult(str(path), "你好", 3.0,
                            [CharTimestamp("你", .2, .5), CharTimestamp("好", .5, .9)])


def test_actual_non_aac_export_preserves_size_and_duration(real_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_with_cache", fake_transcript)
    result = pipeline.generate(pipeline.GenerateOptions(str(real_video), str(tmp_path / "输出's")))
    output = result["output_media"]
    assert output["video_codec"] == "h264" and output["audio_codec"] == "aac"
    assert (output["width"], output["height"]) == (320, 180)
    assert abs(output["duration"] - 3.0) <= .05
    # Decode both streams, not only the container header.
    run_process([tool("ffmpeg"), "-v", "error", "-i", result["video"], "-f", "null", "-"])


def test_rotation_metadata_is_respected(real_video, tmp_path, monkeypatch):
    rotated = tmp_path / "竖屏.mov"
    run_process([tool("ffmpeg"), "-y", "-display_rotation:v:0", "90",
                 "-i", real_video, "-c", "copy", rotated])
    assert inspect_media(rotated)["direction"] == "竖屏"
    monkeypatch.setattr(pipeline, "transcribe_with_cache", fake_transcript)
    result = pipeline.generate(pipeline.GenerateOptions(str(rotated), str(tmp_path / "results")))
    assert (result["output_media"]["width"], result["output_media"]["height"]) == (180, 320)


def test_invalid_file_has_clear_media_failure(tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a movie")
    with pytest.raises(MediaError):
        inspect_media(bad)


def test_audio_detector_does_not_infer_silence_from_no_asr_text(real_video):
    assert verified_silences(str(real_video), 3.0) == []
