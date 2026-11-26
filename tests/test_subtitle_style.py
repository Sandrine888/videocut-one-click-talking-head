import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from videocut.output.styled import burn_subtitles, read_srt
from videocut.subtitle_style import SubtitleCue, build_ass, check_layout, layout_cue, load_style, visible_count


class SubtitleStyleTests(unittest.TestCase):
    def setUp(self):
        self.vertical = load_style(720, 1280)
        self.horizontal = load_style(1280, 720)
        self.cue = SubtitleCue("7", 1234, 3001, "短句")

    def test_profiles_and_short_caption(self):
        self.assertEqual((self.vertical.max_chars, self.horizontal.max_chars), (16, 22))
        self.assertEqual((self.vertical.margin_x, self.vertical.margin_y), (58, 192))
        self.assertEqual((self.horizontal.margin_x, self.horizontal.margin_y), (103, 108))
        self.assertEqual((self.vertical.fade_in_ms, self.horizontal.chapter_badge_ms), (120, 1200))
        self.assertTrue(check_layout(self.cue, ("短句",), self.vertical)["ok"])

    def test_checks_boundaries_with_structured_reason(self):
        for style in (self.vertical, self.horizontal):
            accepted = check_layout(self.cue, ("测" * style.max_chars,), style)
            long = check_layout(self.cue, ("测" * (style.max_chars + 1),), style)
            three = check_layout(self.cue, ("甲", "乙", "丙"), style)
            self.assertTrue(accepted["ok"])
            self.assertEqual(long["issues"][0]["code"], "too_many_characters")
            self.assertEqual(three["issues"][0]["code"], "too_many_lines")
            self.assertEqual((long["cue_id"], long["start_ms"]), ("7", 1234))

    def test_wrap_preserves_protected_tokens_and_punctuation(self):
        text = "先确认纳斯达克交易所，再看LLM处理120毫秒的数据"
        cue = SubtitleCue("1", 0, 3000, text)
        lines = layout_cue(cue, self.vertical, protected_terms=("纳斯达克交易所",))
        self.assertEqual(len(lines), 2)
        self.assertEqual("".join(lines), text)
        for atom in ("纳斯达克交易所", "LLM", "120毫秒"):
            self.assertTrue(any(atom in line for line in lines))
        self.assertFalse(lines[1].startswith("，"))
        self.assertTrue(check_layout(cue, lines, self.vertical)["ok"])

    def test_ass_uses_exact_rows_and_centisecond_rounding(self):
        cue = SubtitleCue("x", 1234, 3001, "这是一行\n这是另一行")
        ass, report = build_ass([cue], self.vertical)
        self.assertIn("WrapStyle: 2", ass)
        self.assertIn("0:00:01.23,0:00:03.00", ass)
        self.assertIn(r"这是一行\N这是另一行", ass)
        self.assertEqual(report[0]["lines"], ["这是一行", "这是另一行"])
        self.assertEqual(visible_count(" 课，A\u0301 "), 3)

    def test_unbreakable_input_reports_failure_without_truncating(self):
        cue = SubtitleCue("x", 0, 2000, "A" * 36)
        ass, report = build_ass([cue], self.vertical)
        self.assertNotIn("Dialogue:", ass)
        self.assertEqual(report[0]["lines"], [cue.text])
        self.assertFalse(report[0]["ok"])

    def test_accent_is_one_whole_term_without_changing_layout(self):
        cue = SubtitleCue("x", 0, 2000, "ASR2 和 LLM，然后 ASR")
        ass, report = build_ass([cue], self.vertical, accent_terms=("ASR", "LLM"))
        self.assertEqual(report[0]["lines"], [cue.text])
        self.assertEqual(report[0]["accent"], "ASR")
        face_event = next(line for line in ass.splitlines() if line.startswith("Dialogue: 1"))
        self.assertTrue(face_event.endswith(r"{\1c&H96DAFF&}ASR{\1c&HEEF9FF&}"))
        self.assertEqual(face_event.count(r"\1c"), 2)

    def test_source_han_enables_bold_accent_and_separate_opening_title(self):
        style = load_style(720, 1280, font="Source Han Sans SC Medium")
        cue = SubtitleCue("1", 1234, 3001, "测试 ASR 字幕")
        ass, report = build_ass(
            [cue], style, accent_terms=("ASR",), source_han=True, opening_title=r"剪辑 {样片}",
        )
        self.assertIn(r"\fnSource Han Sans SC\b700}ASR", ass)
        self.assertIn(r"\fnSource Han Sans SC Medium\b0}", ass)
        self.assertIn(r"剪辑 \{样片\}", ass)
        self.assertIn("Dialogue: 2,0:00:00.25,0:00:03.05", ass)
        self.assertIn("Dialogue: 1,0:00:01.23,0:00:03.00", ass)
        self.assertEqual(report[0]["accent"], "ASR")

    def test_source_han_rejects_missing_assets_before_burn_in(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Missing Source Han font"):
                burn_subtitles(root / "a.mp4", root / "a.srt", root / "b.mp4", source_han_dir=root)

    def test_opening_title_rejects_invalid_text(self):
        with self.assertRaisesRegex(ValueError, "single line"):
            build_ass([], self.vertical, source_han=True, opening_title="第一行\n第二行")
        with self.assertRaisesRegex(ValueError, "requires"):
            build_ass([], self.vertical, opening_title="剪辑")

    def test_utf8_bom_and_exact_millisecond_timing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "example.srt"
            path.write_text("7\n00:00:01,234 --> 00:00:03,001\n短句\n", encoding="utf-8-sig")
            self.assertEqual(read_srt(path), [self.cue])
            path.write_text("7\n00:00:03,001 --> 00:00:01,234\n短句\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ends before"):
                read_srt(path)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are required")
    def test_burn_from_unicode_path_and_keep_existing_output_on_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, srt, out, report = (root / name for name in ("试验 源.mp4", "字幕.srt", "成片.mp4", "结果.json"))
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=320x568:r=24:d=1", "-c:v", "libx264", str(source)],
                check=True, capture_output=True,
            )
            srt.write_text("1\n00:00:00,000 --> 00:00:00,900\n静态字幕\n", encoding="utf-8")
            result = burn_subtitles(source, srt, out, report_path=report)
            self.assertTrue(result["ok"])
            self.assertTrue(result["rendered"])
            self.assertGreater(out.stat().st_size, 0)
            previous = out.read_bytes()
            srt.write_text("1\n00:00:00,000 --> 00:00:00,900\n甲\n乙\n丙\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "failed layout"):
                burn_subtitles(source, srt, out, report_path=report)
            self.assertEqual(out.read_bytes(), previous)
            failed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(failed["failed_cues"], 1)
            self.assertFalse(failed["rendered"])
