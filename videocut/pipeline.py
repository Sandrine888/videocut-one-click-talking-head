"""B-owned noninteractive workflow; UI and CLI use this exact function."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import traceback
from typing import Callable, Optional
import uuid

from .media import check_tools, inspect_media, render_video, verified_silences
from .transcribe import transcribe_with_cache
from .subtitle_style import load_template

STAGES = ("识别", "字幕", "动效", "导出")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as handle:
        pending = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


@dataclass
class GenerateOptions:
    video: str
    output_dir: str = "results"
    trim_silence: bool = False
    template: Optional[str] = None
    model_name: str = "paraformer-zh"
    segment_length: int = 30
    silence_threshold: float = 1.8
    silence_padding: float = 0.25
    mode: str = "quick"
    auto_apply: bool = False
    review_task: Optional[str] = None
    selected_ids: tuple = ()


@dataclass
class PipelineAdapters:
    # A: () -> JSON-serializable template
    template_loader: Optional[Callable] = None
    # C: (TranscriptResult, template) -> SubtitleSegment[]
    subtitle_builder: Optional[Callable] = None
    # D: (SubtitleSegment[], template, task_dir, media) -> ASS/SRT Path
    effect_builder: Optional[Callable] = None
    # E: (result_manifest) -> six-category quality report
    verifier: Optional[Callable] = None


def load_adapters(spec=None):
    if not spec:
        return PipelineAdapters()
    module, separator, factory = spec.partition(":")
    if not separator:
        raise ValueError("适配器请使用 模块名:工厂函数 格式。")
    adapters = getattr(importlib.import_module(module), factory)()
    if not isinstance(adapters, PipelineAdapters):
        raise TypeError("适配器工厂必须返回 PipelineAdapters。")
    return adapters


class GenerationError(RuntimeError):
    def __init__(self, stage, message, task_dir):
        super().__init__(message)
        self.stage, self.task_dir = stage, str(task_dir)


def canonical_segments(segments, duration):
    from .output.local import SubtitleSegment
    result, previous_end = [], 0.0
    for number, value in enumerate(segments, 1):
        value = value if isinstance(value, SubtitleSegment) else SubtitleSegment(**value)
        start, end = round(float(value.start), 3), round(float(value.end), 3)
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                or end <= start or start < previous_end or end > duration + 0.05
                or not isinstance(value.text, str) or not value.text.strip()
                or "\n\n" in value.text or "\r" in value.text):
            raise ValueError(f"第 {number} 条字幕的文本或时间轴无效，请检查字幕模块。")
        result.append(SubtitleSegment(number, start, end, value.text))
        previous_end = end
    if not result:
        raise ValueError("没有可用字幕，请检查原片是否包含可识别的口播。")
    return result


def write_srt(segments, path):
    def timestamp(seconds):
        millis = round(seconds * 1000)
        hours, millis = divmod(millis, 3600000)
        minutes, millis = divmod(millis, 60000)
        secs, millis = divmod(millis, 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
    Path(path).write_text("\n\n".join(
        f"{s.index}\n{timestamp(s.start)} --> {timestamp(s.end)}\n{s.text}"
        for s in segments) + "\n", encoding="utf-8")


def generate(options, *, adapters=None, on_event=None, task_id=None):
    """Produce checked outputs or raise GenerationError. Never prompts for input."""
    adapters = adapters or PipelineAdapters()
    task_id = task_id or uuid.uuid4().hex
    if not task_id.isalnum() or len(task_id) > 64:
        raise ValueError("任务标识无效。")
    task_dir = Path(options.output_dir).resolve() / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    stage, started, stage_started = "校验", time.monotonic(), time.monotonic()
    timings = {}
    warnings = []
    integration = {"A": True,
                   "C": bool(adapters.subtitle_builder),
                   "D": bool(adapters.effect_builder), "E": bool(adapters.verifier)}
    events = []

    def emit(name, status, message):
        nonlocal stage, stage_started
        now = time.monotonic()
        if name != stage:
            timings[stage] = round(now - stage_started, 3)
            stage_started, stage = now, name
        event = dict(task_id=task_id, stage=name, status=status, message=message,
                     elapsed_seconds=round(now - started, 3),
                     timestamp=datetime.now(timezone.utc).isoformat())
        events.append(event)
        write_json(task_dir / "progress.json", events)
        if on_event:
            on_event(event)

    try:
        emit("校验", "running", "正在检查视频和处理环境。")
        if type(options.trim_silence) is not bool:
            raise ValueError("自动删停顿必须是开启或关闭。")
        if options.mode not in ("quick", "advanced") or type(options.auto_apply) is not bool:
            raise ValueError("无效的剪辑模式。")
        if options.mode == "quick" and (options.auto_apply or options.review_task or options.selected_ids):
            raise ValueError("快剪不接受 AI 删减参数。")
        if options.selected_ids and not options.review_task or options.review_task and options.auto_apply:
            raise ValueError("请选择一种应用建议的方式。")
        check_tools()
        media = inspect_media(options.video)
        if options.template:
            template = json.loads(Path(options.template).read_text(encoding="utf-8-sig"))
        elif adapters.template_loader:
            template = adapters.template_loader()
        else:
            template = {}
        if not isinstance(template, dict):
            raise ValueError("模板配置必须是一个对象。")
        template = load_template(template)
        write_json(task_dir / "effective_config.json",
                   dict(options=asdict(options), template=template, integration=integration))
        write_json(task_dir / "input_media.json", media)
        emit("校验", "completed", f"检查通过：{media['direction']}，{media['duration']:.1f} 秒。")

        emit("识别", "running", "正在准备本地语音识别，首次加载模型可能较慢。")
        cache_hit = False

        def recognition_event(kind, message):
            nonlocal cache_hit
            if kind == "cache_hit":
                cache_hit = True
                emit("识别", "running", "正在使用匹配的已有识别结果。")
            elif kind == "cache_invalid":
                emit("识别", "running", "已有识别结果不匹配，正在重新识别。")

        transcript = transcribe_with_cache(
            media["path"], cache_dir=Path(options.output_dir).resolve() / "cache",
            config=dict(model_name=options.model_name, segment_length=options.segment_length),
            on_event=recognition_event, local_only=True)
        if not transcript.chars:
            raise ValueError("未识别到语音，请选择包含清晰口播的原片。")
        if abs(transcript.duration - media["duration"]) > 0.2:
            raise ValueError("识别结果与原片时长不一致，请重新识别。")
        transcript.save(str(task_dir / "transcript.json"))
        deleted, effective_video = [], media["path"]
        suggestions, chosen = [], []
        if options.mode == "advanced":
            if options.review_task:
                previous = options.review_task
                if not isinstance(previous, str) or len(previous) != 32 or not previous.isalnum():
                    raise ValueError("建议来源无效。")
                review_dir = task_dir.parent / previous
                review = json.loads((review_dir / "result.json").read_text(encoding="utf-8"))
                original = json.loads((review_dir / "transcript.json").read_text(encoding="utf-8"))
                if review.get("mode") != "advanced" or review.get("action") != "review" or original != transcript.to_dict():
                    raise ValueError("原片或转写已改变，请重新生成建议。")
                suggestions = review["suggestions"]
                ids = options.selected_ids
                if not ids or any(type(i) is not int for i in ids) or not set(ids) <= {r['id'] for r in suggestions}:
                    raise ValueError("请选择有效的建议。")
                chosen = [row for row in suggestions if row["id"] in ids]
            else:
                from .advanced import analyze
                emit("识别", "running", "正在分析口播内容，查找可以精简的原话。")
                suggestions = analyze(transcript)
                if options.auto_apply:
                    chosen = suggestions
        if options.trim_silence:
            emit("识别", "running", "正在检测长停顿。")
            ranges = verified_silences(media["path"], media["duration"],
                                       threshold=options.silence_threshold, padding=options.silence_padding)
            deleted = [dict(start=s, end=e) for s, e in ranges if not any(
                c.start < e and c.end > s for c in transcript.chars)]
        deleted.extend(dict(start=row['start'], end=row['end'], suggestion_id=row['id']) for row in chosen)
        deleted.sort(key=lambda item: item['start'])
        if deleted:
            from .slip_detect import DeleteTask, SlipType
            from .editor import cut_video, calculate_keep_segments
            from .commands.cut_cmd import remap_transcript_for_cut
            tasks = [DeleteTask(SlipType.REPLACE if 'suggestion_id' in r else SlipType.SILENCE,
                                r['start'], r['end'], '', '') for r in deleted]
            keeps = calculate_keep_segments(tasks, transcript.duration)
            if not keeps or sum(s.duration for s in keeps) < 0.2:
                raise ValueError("剪辑将删除全部内容，请保留更多片段。")
            effective_video = str(task_dir / "trimmed.mp4")
            if not cut_video(media["path"], effective_video, tasks, transcript.duration):
                raise RuntimeError("剪辑失败，请查看日志后重试。")
            transcript = remap_transcript_for_cut(transcript, tasks)
        write_json(task_dir / "deletions.json", deleted)
        transcript.save(str(task_dir / "mapped_transcript.json"))
        emit("识别", "completed", "语音识别完成。" +
             (f"已剪去 {len(deleted)} 处。" if deleted else "保留全部原片内容。"))

        emit("字幕", "running", "正在整理字幕与时间轴。")
        if adapters.subtitle_builder:
            segments = adapters.subtitle_builder(transcript, template)
        else:
            from .output.local import create_subtitle_segments
            segments = create_subtitle_segments(transcript.chars)
        segments = canonical_segments(segments, transcript.duration)
        srt_path = task_dir / "subtitles.srt"
        write_srt(segments, srt_path)
        write_json(task_dir / "subtitles.json", [asdict(s) for s in segments])
        emit("字幕", "completed", f"字幕已生成，共 {len(segments)} 条。")

        emit("动效", "running", "正在准备字幕渲染。")
        layout_report = None
        if adapters.effect_builder:
            asset = Path(adapters.effect_builder(segments, template, task_dir, media)).resolve()
            if asset.suffix.lower() not in {".srt", ".ass"} or not asset.is_file():
                raise ValueError("动效模块没有提供有效的 ASS 或 SRT 渲染文件。")
        else:
            from .output.styled import prepare_subtitles
            asset, layout_report = prepare_subtitles(segments, template, task_dir, media)
        missing = [name for name, connected in integration.items() if not connected]
        if missing:
            warnings.append("联调版本：" + "、".join(missing) + " 模块尚未正式接入，未通过全队成片验收。")
        emit("动效", "completed", "动效文件已准备。" if adapters.effect_builder
             else "已准备 A 的静态字幕排版，动效模块尚未接入。")

        emit("导出", "running", "正在渲染视频，完成后检查输出文件。")
        final_path = task_dir / "final.mp4"
        render_video(effective_video, asset, final_path)
        output_media = inspect_media(final_path)
        tolerance = max(1.0 / media["fps"] if media["fps"] else 0.05, 0.05)
        if (output_media["video_codec"] != "h264" or output_media["audio_codec"] != "aac"
                or output_media["width"] != media["width"]
                or output_media["height"] != media["height"]
                or abs(output_media["duration"] - transcript.duration) > tolerance + 0.001
                or not srt_path.stat().st_size):
            raise ValueError("导出文件的编码、画幅或时长不符合预期，请查看详细日志。")
        timings[stage] = round(time.monotonic() - stage_started, 3)
        result = dict(task_id=task_id, status="completed",
                      completion_level="integrated" if not missing else "integration",
                      mode=options.mode, suggestions=suggestions, applied_ids=[r['id'] for r in chosen],
                      action=('quick' if options.mode == 'quick' else 'apply' if options.auto_apply or options.review_task else 'review'),
                      task_dir=str(task_dir), video=str(final_path), srt=str(srt_path),
                      subtitle_asset=str(asset), layout_report=str(layout_report) if layout_report else None,
                      subtitles=str(task_dir / "subtitles.json"), input_media=media,
                      output_media=output_media, trim_silence=options.trim_silence,
                      deletions=deleted, cache_hit=cache_hit, integration=integration,
                      warnings=warnings, stage_seconds=timings,
                      elapsed_seconds=round(time.monotonic() - started, 3))
        # E owns semantic/visual verification; this baseline never claims it ran.
        checks = [{"category": name, "status": "not_tested"} for name in
                  ("字幕准确", "断句与标点", "同步与时间轴", "视觉与动效", "输出完整", "速度与可靠性")]
        checks[4].update(status="partial", message="B 已核验编码、画幅、时长与文件；独立播放和 SRT 视觉对照待 E 核验。")
        if layout_report:
            checks[3].update(status="partial", message="已检查 A 字幕的行数和估算宽度；实际画面、遮挡和动效仍待核验。")
        report = {"owner": "B 联调基础检查，尚非 E 正式自检", "checks": checks}
        if adapters.verifier:
            try:
                verified_report = adapters.verifier(dict(result))
                if not isinstance(verified_report, dict):
                    raise ValueError("自检模块必须返回报告对象。")
                json.dumps(verified_report, ensure_ascii=False, allow_nan=False)
                report = verified_report
            except Exception as exc:
                warnings.append(f"自检模块运行失败，成片已保存，请重新自检：{exc}")
                report["error"] = str(exc)
        write_json(task_dir / "checks.json", report)
        result["checks"] = str(task_dir / "checks.json")
        write_json(task_dir / "result.json", result)
        emit("导出", "completed", "联调视频已生成，请查看尚未接入的模块。" if missing else "视频已生成，请预览并检查。")
        return result
    except Exception as exc:
        (task_dir / "result.json").unlink(missing_ok=True)
        (task_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        error = dict(task_id=task_id, status="failed", stage=stage, message=str(exc),
                     next_action="请修正输入或查看详细日志后重试；原片未被覆盖。",
                     log=str(task_dir / "error.log"), task_dir=str(task_dir))
        write_json(task_dir / "error.json", error)
        emit(stage, "failed", str(exc))
        raise GenerationError(stage, str(exc), task_dir) from exc
