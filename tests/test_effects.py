"""D 模块（render/effects.py）单元测试 —— PRD AC1/AC2 的机械检查。"""

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