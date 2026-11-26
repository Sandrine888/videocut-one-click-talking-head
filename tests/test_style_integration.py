"""Verify that A styles the same final subtitles consumed by B's two modes."""
import json
from pathlib import Path

import pytest

from videocut import pipeline
from videocut.output.local import SubtitleSegment
from tests.test_generate import workflow


def test_style_uses_final_cues_and_converts_seconds_only_at_render_boundary(workflow):
    text = "先确认纳斯达克交易所，再看LLM处理120毫秒的数据"
    adapters = pipeline.PipelineAdapters(
        subtitle_builder=lambda t, c: [SubtitleSegment(1, .234, 1.876, text)],
        template_loader=lambda: {"protected_terms": ["纳斯达克交易所"], "accent_terms": ["LLM"]},
    )
    result = pipeline.generate(workflow, adapters=adapters)
    report = json.loads(Path(result["layout_report"]).read_text(encoding="utf-8"))
    cue = report["cues"][0]
    assert result["integration"]["A"] is True
    assert (cue["start_ms"], cue["end_ms"]) == (234, 1876)
    assert "".join(cue["lines"]) == text
    assert len(cue["lines"]) == 2 and cue["accent"] == "LLM"
    assert any("纳斯达克交易所" in line for line in cue["lines"])
    ass = Path(result["subtitle_asset"]).read_text(encoding="utf-8")
    assert "RoleA" in ass and "0:00:00.23,0:00:01.88" in ass
    assert "00:00:00,234 --> 00:00:01,876" in Path(result["srt"]).read_text(encoding="utf-8")
    assert json.loads(Path(result["subtitles"]).read_text(encoding="utf-8"))[0]["text"] == text


def test_template_override_is_effective_and_does_not_mutate_default(workflow):
    adapters = pipeline.PipelineAdapters(template_loader=lambda: {
        "text_color": "#ABCDEF", "landscape": {"max_chars": 20},
    })
    first = pipeline.generate(workflow, adapters=adapters)
    report = json.loads(Path(first["layout_report"]).read_text(encoding="utf-8"))
    style = report["style"]
    assert style["text_color"] == "#ABCDEF" and style["max_chars"] == 20
    assert style["target_min_chars"] == 16
    config = json.loads((Path(first["task_dir"]) / "effective_config.json").read_text(encoding="utf-8"))
    assert config["template"]["text_color"] == style["text_color"]
    second = pipeline.generate(workflow)
    default = json.loads(Path(second["layout_report"]).read_text(encoding="utf-8"))["style"]
    assert default["text_color"] == "#FFF9EE" and default["max_chars"] == 22


def test_layout_failure_keeps_diagnostics_and_blocks_export(workflow):
    adapters = pipeline.PipelineAdapters(
        subtitle_builder=lambda t, c: [SubtitleSegment(1, .2, 1.1, "A" * 80)],
    )
    with pytest.raises(pipeline.GenerationError, match="字幕排版失败") as error:
        pipeline.generate(workflow, adapters=adapters)
    directory = Path(error.value.task_dir)
    assert not (directory / "final.mp4").exists()
    assert not (directory / "result.json").exists()
    report = json.loads((directory / "layout.json").read_text(encoding="utf-8"))
    assert report["failed_cues"] == 1 and not report["ok"]
    assert report["cues"][0]["lines"] == ["A" * 80]
