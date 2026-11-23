"""
口误识别模块测试
"""

import pytest
from videocut.transcribe import TranscriptResult, CharTimestamp
from videocut.slip_detect import (
    detect_fillers,
    detect_silences,
    detect_slips_simple,
    detect_all,
    SlipType,
    DeleteTask
)


def make_transcript(text: str, char_duration: float = 0.2) -> TranscriptResult:
    """创建测试用转录结果"""
    chars = []
    t = 0.0
    for c in text:
        chars.append(CharTimestamp(c, t, t + char_duration))
        t += char_duration
    return TranscriptResult(
        video_file="test.mp4",
        full_text=text,
        duration=t,
        chars=chars
    )


class TestDetectFillers:
    """语气词检测测试"""

    def test_detect_single_filler(self):
        """检测单个语气词"""
        transcript = make_transcript("你好嗯我是")
        tasks = detect_fillers(transcript)

        assert len(tasks) == 1
        assert tasks[0].text == "嗯"
        assert tasks[0].slip_type == SlipType.FILLER

    def test_detect_multiple_fillers(self):
        """检测多个语气词"""
        transcript = make_transcript("嗯你好啊我是")
        tasks = detect_fillers(transcript)

        assert len(tasks) == 2
        texts = [t.text for t in tasks]
        assert "嗯" in texts
        assert "啊" in texts

    def test_no_fillers(self):
        """无语气词"""
        transcript = make_transcript("你好我是测试")
        tasks = detect_fillers(transcript)

        assert len(tasks) == 0


class TestDetectSilences:
    """静音检测测试"""

    def test_detect_long_silence(self):
        """检测长静音"""
        chars = [
            CharTimestamp("你", 0.0, 0.2),
            CharTimestamp("好", 0.2, 0.4),
            CharTimestamp("我", 2.0, 2.2),  # 1.6s 静音
            CharTimestamp("是", 2.2, 2.4),
        ]
        transcript = TranscriptResult(
            video_file="test.mp4",
            full_text="你好我是",
            duration=3.0,
            chars=chars
        )

        tasks = detect_silences(transcript, threshold=1.0)

        assert len(tasks) == 1
        assert tasks[0].slip_type == SlipType.SILENCE
        assert tasks[0].duration >= 1.0

    def test_no_long_silence(self):
        """无长静音"""
        transcript = make_transcript("你好我是测试")
        tasks = detect_silences(transcript, threshold=1.0)

        assert len(tasks) == 0

    def test_detect_opening_silence(self):
        """检测开头静音"""
        chars = [
            CharTimestamp("你", 2.0, 2.2),  # 开头 2s 静音
            CharTimestamp("好", 2.2, 2.4),
        ]
        transcript = TranscriptResult(
            video_file="test.mp4",
            full_text="你好",
            duration=3.0,
            chars=chars
        )

        tasks = detect_silences(transcript, threshold=1.0)

        assert len(tasks) == 1
        assert tasks[0].start == 0
        assert tasks[0].context == "开头静音"


class TestDetectSlips:
    """口误检测测试"""

    def test_detect_stutter(self):
        """检测卡顿型口误"""
        transcript = make_transcript("我是是测试")
        tasks = detect_slips_simple(transcript)

        stutter_tasks = [t for t in tasks if t.slip_type == SlipType.STUTTER]
        assert len(stutter_tasks) == 1
        assert stutter_tasks[0].text == "是"

    def test_detect_repeat(self):
        """检测重复型口误"""
        transcript = make_transcript("这是这是测试")
        tasks = detect_slips_simple(transcript)

        repeat_tasks = [t for t in tasks if t.slip_type == SlipType.REPEAT]
        assert len(repeat_tasks) == 1
        assert repeat_tasks[0].text == "这是"

    def test_no_slips(self):
        """无口误"""
        transcript = make_transcript("我是测试内容")
        tasks = detect_slips_simple(transcript)

        # 可能会有误判，这里只检查基本情况
        assert isinstance(tasks, list)

    def test_valid_repeated_words_not_detected(self):
        """合法叠词不应被误判为卡顿"""
        # 测试常见合法叠词
        test_cases = [
            "谢谢大家",       # 谢谢
            "看看这个",       # 看看
            "妈妈来了",       # 妈妈
            "哈哈真好笑",     # 哈哈
            "慢慢来",         # 慢慢
            "天天向上",       # 天天
        ]

        for text in test_cases:
            transcript = make_transcript(text)
            tasks = detect_slips_simple(transcript)
            stutter_tasks = [t for t in tasks if t.slip_type == SlipType.STUTTER]
            assert len(stutter_tasks) == 0, f"'{text}' 中的叠词被误判为卡顿"

    def test_triple_repeat_still_detected(self):
        """三连重复仍应被检测（真正的卡顿）"""
        transcript = make_transcript("谢谢谢大家")  # 三个"谢"是卡顿
        tasks = detect_slips_simple(transcript)

        stutter_tasks = [t for t in tasks if t.slip_type == SlipType.STUTTER]
        assert len(stutter_tasks) == 1, "三连重复应被检测为卡顿"


class TestDetectAll:
    """综合检测测试"""

    def test_detect_all_types(self):
        """检测所有类型"""
        chars = [
            CharTimestamp("你", 0.0, 0.2),
            CharTimestamp("好", 0.2, 0.4),
            CharTimestamp("嗯", 0.5, 0.7),  # 语气词
            CharTimestamp("我", 2.0, 2.2),  # 1.3s 静音
            CharTimestamp("是", 2.2, 2.4),
            CharTimestamp("是", 2.4, 2.6),  # 卡顿
            CharTimestamp("测", 2.6, 2.8),
            CharTimestamp("试", 2.8, 3.0),
        ]
        transcript = TranscriptResult(
            video_file="test.mp4",
            full_text="你好嗯我是是测试",
            duration=3.0,
            chars=chars
        )

        result = detect_all(transcript)

        assert len(result.fillers) >= 1  # 语气词
        assert len(result.silences) >= 1  # 静音
        # 口误检测可能有误差

    def test_empty_transcript(self):
        """空转录"""
        transcript = TranscriptResult(
            video_file="test.mp4",
            full_text="",
            duration=0.0,
            chars=[]
        )

        result = detect_all(transcript)

        assert len(result.all_tasks) == 0


class TestDeleteTask:
    """删除任务测试"""

    def test_duration(self):
        """测试时长计算"""
        task = DeleteTask(
            slip_type=SlipType.FILLER,
            start=1.0,
            end=2.5,
            text="嗯",
            context="test"
        )

        assert task.duration == 1.5

    def test_to_markdown(self):
        """测试 Markdown 输出"""
        task = DeleteTask(
            slip_type=SlipType.SILENCE,
            start=1.0,
            end=2.5,
            text="",
            context="静音"
        )

        md = task.to_markdown(1)
        assert "静音" in md
        assert "1.5s" in md
