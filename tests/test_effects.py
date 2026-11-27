"""D 模块（render/effects.py）单元测试 —— PRD AC1/AC2 的机械检查 + v1.2 接口契约。"""

from pathlib import Path

import pysubs2
import pytest

from videocut.render import effects as fx


def test_pick_highlight_glossary_first():
    assert fx.pick_highlight_word("今天聊聊 FunASR 的用法。") == "FunASR"


def test_pick_highlight_number_fallback():
    assert fx.pick_highlight_word("这个功能提升了 30% 的效率。") == "30%"


def test_pick_highlight_none():
    assert fx.pick_highlight_word("我们下期再见。") is None


def test_pick_highlight_earliest_term_wins():
    # 两个术语都在时取最先出现的
    assert fx.pick_highlight_word("先说 ASS 再说 SRT") == "ASS"


def test_fade_clamp():
    tpl = fx._deep_merge(fx.DEFAULT_TEMPLATE, {"effects": {"fade_in_ms": 500}})
    # load_template 需要文件，这里直接验证钳制逻辑入口
    import json, tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(tpl, f)
        p = f.name
    try:
        loaded = fx.load_template(p)
        assert loaded["effects"]["fade_in_ms"] == 150
    finally:
        os.unlink(p)


def _events(subs):
    return [e for e in subs if e.style == "Default"]


def test_build_ass_fade_and_highlight_counts():
    tpl = fx.load_template()
    subs = fx.build_ass(fx.DEMO_SEGMENTS, tpl, fx.DEMO_CHAPTERS, effects_on=True)
    segs = _events(subs)
    assert len(segs) == len(fx.DEMO_SEGMENTS)
    # AC1: 每条都有 \fad，且 80<=N<=150
    for e in segs:
        m = fx._FAD_RE.search(e.text)
        assert m, e.text
        assert 80 <= int(m.group(1)) <= 150
    # AC2: 每条高亮标签 <=1
    hl_tag = "{\\c" + fx._inline_color(tpl["colors"]["highlight"]) + "}"
    for e in segs:
        assert e.text.count(hl_tag) <= 1


def test_noeffects_has_no_tags_and_same_timeline():
    tpl = fx.load_template()
    on = fx.build_ass(fx.DEMO_SEGMENTS, tpl, fx.DEMO_CHAPTERS, effects_on=True)
    off = fx.build_ass(fx.DEMO_SEGMENTS, tpl, fx.DEMO_CHAPTERS, effects_on=False)
    on_segs, off_segs = _events(on), _events(off)
    # AC4: 时间轴逐条一致
    assert [(e.start, e.end) for e in on_segs] == [(e.start, e.end) for e in off_segs]
    for e in off_segs:
        assert "\\fad" not in e.text and "\\c" not in e.text
    # 无动效版没有角标
    assert not any(e.style == "Badge" for e in off)
    assert any(e.style == "Badge" for e in on)


def test_badge_shrink_when_speaking():
    tpl = fx.load_template()
    subs = fx.build_ass(fx.DEMO_SEGMENTS, tpl, fx.DEMO_CHAPTERS, effects_on=True)
    badges = [e for e in subs if e.style == "Badge"]
    assert len(badges) == len(fx.DEMO_CHAPTERS)
    # demo 中两个章节都与说话时段重叠 -> 都带缩小标签
    for b in badges:
        assert "\\fs" in b.text and "\\1a&H80&" in b.text


def test_wrap_max_two_lines_demo():
    tpl = fx.load_template()
    for seg in fx.DEMO_SEGMENTS:
        lines = fx.wrap_text(seg["text"], tpl["chars_per_line"]["portrait"][1])
        assert len(lines) <= 2


# ---------------------------------------------------------------------------
# v1.2 跨模块接口契约（docs/D模块_接口契约.md）
# ---------------------------------------------------------------------------

def test_error_hierarchy():
    assert issubclass(fx.InputError, (fx.EffectsError, ValueError))
    assert issubclass(fx.MediaError, (fx.EffectsError, RuntimeError))
    assert issubclass(fx.RenderError, (fx.EffectsError, RuntimeError))


def test_validate_segments_normalizes():
    segs = fx.validate_segments([{"start": 0, "end": 1.5, "text": " 你好 "}])
    assert segs == [{"index": 1, "start": 0.0, "end": 1.5, "text": "你好"}]


@pytest.mark.parametrize("bad", [
    [],
    "not-a-list",
    [{}],                                                     # 缺 start/end/text
    [{"start": 2.0, "end": 2.0, "text": "a"}],                # end == start
    [{"start": -1.0, "end": 2.0, "text": "a"}],               # 负时间
    [{"start": 1.0, "end": 2.0, "text": ""}],                 # 空文本
    [{"start": "1.0", "end": 2.0, "text": "a"}],              # 时间类型错
    [{"index": 1.5, "start": 0.0, "end": 1.0, "text": "a"}],  # index 非整数
])
def test_validate_segments_errors(bad):
    with pytest.raises(fx.InputError):
        fx.validate_segments(bad)


def test_validate_chapters():
    assert fx.validate_chapters(None) == []
    assert fx.validate_chapters([]) == []
    with pytest.raises(fx.InputError):
        fx.validate_chapters([{"start": 5.0, "label": "b"}, {"start": 1.0, "label": "a"}])  # 非递增
    with pytest.raises(fx.InputError):
        fx.validate_chapters([{"start": 1.0}])  # 缺 label
    with pytest.raises(fx.InputError):
        fx.validate_chapters([{"start": 1.0, "label": "  "}])  # 空白 label


def test_build_ass_rejects_bad_inputs():
    tpl = fx.load_template()
    with pytest.raises(fx.InputError):
        fx.build_ass([{"start": 1.0, "end": 2.0}], tpl)          # 缺 text
    with pytest.raises(fx.InputError):
        fx.build_ass(fx.DEMO_SEGMENTS, tpl, [{"start": -1, "label": "x"}])
    with pytest.raises(fx.InputError):
        fx.build_ass(fx.DEMO_SEGMENTS, "not-a-dict")


def test_load_template_accepts_dict_and_validates(tmp_path):
    tpl = fx.load_template({"effects": {"fade_in_ms": 999}})
    assert tpl["effects"]["fade_in_ms"] == 150  # 钳制
    assert fx.load_template({"orientation": "landscape"})["orientation"] == "landscape"
    with pytest.raises(fx.InputError):
        fx.load_template({"orientation": "square"})
    with pytest.raises(fx.InputError):
        fx.load_template({"effects": {"fade_in_ms": "fast"}})
    with pytest.raises(fx.InputError):
        fx.load_template(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(fx.InputError):
        fx.load_template(str(bad))


def test_render_ass_returns_existing_path(tmp_path):
    out = tmp_path / "sub" / "x.ass"
    p = fx.render_ass(fx.DEMO_SEGMENTS, fx.DEFAULT_TEMPLATE,
                      fx.DEMO_CHAPTERS, out_path=str(out))
    assert p == str(out) and Path(p).exists()
    subs = pysubs2.load(str(out), encoding="utf-8")
    assert len([e for e in subs if e.style == "Default"]) == len(fx.DEMO_SEGMENTS)
    assert any(e.style == "Badge" for e in subs)


def test_render_media_error_missing_video():
    with pytest.raises(fx.MediaError):
        fx.render("Z:/definitely/not/here.mp4", fx.DEMO_SEGMENTS)


def test_burn_errors(tmp_path):
    with pytest.raises(fx.MediaError):
        fx.burn("Z:/nope.mp4", str(tmp_path / "a.ass"), str(tmp_path / "o.mp4"))
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a video")
    with pytest.raises(fx.RenderError):
        fx.burn(str(fake), str(fake), str(tmp_path / "o.mp4"))


def test_render_result_to_dict_shape(tmp_path):
    res = fx.RenderResult(orientation="portrait", video="v.mp4",
                          ass_light="l.ass", ass_noeffects="n.ass",
                          mp4_light="l.mp4", mp4_noeffects="n.mp4",
                          report_path=None, checks={"face_block": 0, "edge_touch": 0, "over_two_lines": 0})
    d = res.to_dict()
    assert set(d) == {"orientation", "video", "ass_light", "ass_noeffects",
                      "mp4_light", "mp4_noeffects", "report_path", "checks"}
    assert res.ok and d["checks"]["face_block"] == 0