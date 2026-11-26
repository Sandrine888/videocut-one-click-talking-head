"""B regression tests: no-deletion export, failure truth, cache and job boundary."""
import json
from pathlib import Path
import threading
import time

import pytest

from videocut import pipeline
from videocut.jobs import BusyError, JobManager
from videocut.output.local import SubtitleSegment
from videocut.transcribe import CharTimestamp, TranscriptResult, transcribe_with_cache


def transcript(path="source.mp4"):
    return TranscriptResult(str(path), "你好", 2.0,
                            [CharTimestamp("你", 0.2, 0.7), CharTimestamp("好", 0.7, 1.1)])


@pytest.fixture
def workflow(monkeypatch, tmp_path):
    source = tmp_path / "中文 原片.mp4"
    source.write_bytes(b"source video")
    def inspect(path):
        return dict(path=str(Path(path).resolve()), duration=2.0, width=640, height=360,
                    rotation=0, direction="横屏", fps=25, video_codec="h264", audio_codec="aac")
    monkeypatch.setattr(pipeline, "check_tools", lambda: None)
    monkeypatch.setattr(pipeline, "inspect_media", inspect)
    monkeypatch.setattr(pipeline, "transcribe_with_cache", lambda *args, **kwargs: transcript(source))
    monkeypatch.setattr(pipeline, "render_video", lambda _v, _s, out: Path(out).write_bytes(b"final"))
    def forbidden(*args, **kwargs):
        pytest.fail("Default generation must never detect or delete speech")
    monkeypatch.setattr(pipeline, "verified_silences", forbidden)
    options = pipeline.GenerateOptions(str(source), str(tmp_path / "results"))
    return options


def test_default_preserves_content_and_exports_without_any_deletions(workflow):
    events = []
    result = pipeline.generate(workflow, on_event=events.append)
    assert result["deletions"] == [] and not result["trim_silence"]
    assert Path(result["video"]).read_bytes() == b"final"
    assert "你好" in Path(result["srt"]).read_text(encoding="utf-8")
    assert {e["stage"] for e in events} == {"校验", *pipeline.STAGES}
    assert result["completion_level"] == "integration"
    report = json.loads(Path(result["checks"]).read_text(encoding="utf-8"))
    assert len(report["checks"]) == 6
    assert not any(c["status"] == "passed" for c in report["checks"])


def test_export_failure_never_reports_success(workflow, monkeypatch):
    def fail(*args):
        raise RuntimeError("编码器失败")
    monkeypatch.setattr(pipeline, "render_video", fail)
    events = []
    with pytest.raises(pipeline.GenerationError, match="编码器失败") as error:
        pipeline.generate(workflow, on_event=events.append)
    assert error.value.stage == "导出"
    directory = Path(error.value.task_dir)
    assert not (directory / "result.json").exists()
    assert (directory / "error.log").is_file()
    assert events[-1]["status"] == "failed"


def test_no_speech_is_explicit_failure(workflow, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_with_cache", lambda *a, **k: TranscriptResult("x", "", 2, []))
    with pytest.raises(pipeline.GenerationError, match="未识别到语音"):
        pipeline.generate(workflow)


@pytest.mark.parametrize("segments", [
    [SubtitleSegment(1, -0.1, 1, "错误")],
    [SubtitleSegment(1, 1, 0.5, "错误")],
    [SubtitleSegment(1, 0, 1, "一"), SubtitleSegment(2, .9, 1.5, "二")],
    [SubtitleSegment(1, 0, 3, "越界")],
    [SubtitleSegment(1, float("nan"), 1, "错误")],
    [SubtitleSegment(1, 0, 1, "")],
])
def test_invalid_timeline_is_rejected(segments):
    with pytest.raises(ValueError):
        pipeline.canonical_segments(segments, 2)


def test_shared_subtitle_data_is_given_to_d(workflow):
    seen = []
    segments = [SubtitleSegment(1, 0.2, 1.1, "你好。")]
    def effects(values, template, directory, media):
        seen.extend(values)
        return directory / "subtitles.srt"
    adapters = pipeline.PipelineAdapters(template_loader=lambda: {"name": "test"},
                                         subtitle_builder=lambda t, c: segments, effect_builder=effects)
    result = pipeline.generate(workflow, adapters=adapters)
    data = json.loads(Path(result["subtitles"]).read_text(encoding="utf-8"))
    assert seen[0].text == data[0]["text"] == "你好。"
    assert seen[0].start == data[0]["start"]


def test_invalid_verifier_output_does_not_lose_generated_files(workflow):
    result = pipeline.generate(workflow, adapters=pipeline.PipelineAdapters(verifier=lambda r: None))
    assert Path(result["video"]).is_file()
    assert any("自检模块运行失败" in w for w in result["warnings"])
    report = json.loads(Path(result["checks"]).read_text(encoding="utf-8"))
    assert "error" in report


def test_non_json_verifier_result_is_reported_without_losing_video(workflow):
    adapters = pipeline.PipelineAdapters(verifier=lambda r: {"unsupported": {1, 2}})
    result = pipeline.generate(workflow, adapters=adapters)
    assert Path(result["video"]).is_file()
    report = json.loads(Path(result["checks"]).read_text(encoding="utf-8"))
    assert "error" in report


def test_cache_uses_content_and_recognition_config(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"version1")
    calls = []
    def recognize(path, **kwargs):
        calls.append(kwargs)
        return transcript(path)
    cache = tmp_path / "cache"
    events = []
    for _ in range(2):
        transcribe_with_cache(source, cache_dir=cache, recognizer=recognize,
                              on_event=lambda kind, message: events.append(kind))
    assert len(calls) == 1 and "cache_hit" in events
    source.write_bytes(b"version2")
    transcribe_with_cache(source, cache_dir=cache, recognizer=recognize)
    transcribe_with_cache(source, cache_dir=cache, config={"segment_length": 15}, recognizer=recognize)
    assert len(calls) == 3
    assert len(list(cache.glob("*.transcript.json"))) == 3


def test_legacy_and_broken_cache_are_not_silently_trusted(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".transcript.json").write_text("{}")
    cache = tmp_path / "cache"
    calls = []
    def recognize(path, **kwargs):
        calls.append(path)
        return transcript(path)
    transcribe_with_cache(source, cache_dir=cache, recognizer=recognize)
    next(cache.glob("*.json")).write_text("invalid cache")
    transcribe_with_cache(source, cache_dir=cache, recognizer=recognize)
    assert len(calls) == 2


def test_same_file_content_in_new_location_reuses_cache(tmp_path):
    first, second = tmp_path / "a.mp4", tmp_path / "b.mp4"
    first.write_bytes(b"same"); second.write_bytes(b"same")
    def recognize(path, **kwargs):
        return transcript(path)
    transcribe_with_cache(first, cache_dir=tmp_path / "cache", recognizer=recognize)
    result = transcribe_with_cache(second, cache_dir=tmp_path / "cache",
                                   recognizer=lambda *a, **k: pytest.fail("cache should be reused"))
    assert result.video_file == str(second.resolve())


def test_jobs_prevent_parallel_duplicates_and_keep_status_after_refresh(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def runner(options, **kwargs):
        entered.set(); release.wait(5)
        return {"task_id": kwargs["task_id"]}
    manager = JobManager(tmp_path, runner=runner)
    try:
        first = manager.start(pipeline.GenerateOptions("source.mp4"), request_key="same")
        assert entered.wait(2)
        duplicate = manager.start(pipeline.GenerateOptions("source.mp4"), request_key="same")
        assert duplicate["task_id"] == first["task_id"]
        with pytest.raises(BusyError):
            manager.start(pipeline.GenerateOptions("other.mp4"), request_key="other")
        assert manager.snapshot(first["task_id"])["status"] == "queued"
    finally:
        release.set(); manager.close()
    reloaded = JobManager(tmp_path)
    try:
        assert reloaded.snapshot(first["task_id"])["status"] == "completed"
    finally:
        reloaded.close()


def test_service_restart_marks_interrupted_job_as_failed(tmp_path):
    task_id = "a" * 32
    pipeline.write_json(tmp_path / "jobs" / (task_id + ".json"),
                        {"task_id": task_id, "status": "running"})
    manager = JobManager(tmp_path)
    try:
        assert manager.snapshot(task_id)["status"] == "failed"
    finally:
        manager.close()
