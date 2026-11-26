"""
视频剪辑模块测试
"""

import pytest
from pathlib import Path
from videocut.editor import (
    calculate_keep_segments,
    generate_ffmpeg_filter,
    get_output_path,
    KeepSegment
)
from videocut.slip_detect import DeleteTask, SlipType


def make_delete_task(start: float, end: float) -> DeleteTask:
    """创建测试用删除任务"""
    return DeleteTask(
        slip_type=SlipType.FILLER,
        start=start,
        end=end,
        text="test",
        context="test"
    )


class TestCalculateKeepSegments:
    """保留片段计算测试"""

    def test_no_deletions(self):
        """无删除任务"""
        segments = calculate_keep_segments([], 10.0)

        assert len(segments) == 1
        assert segments[0].start == 0
        assert segments[0].end == 10.0

    def test_single_deletion(self):
        """单个删除任务"""
        tasks = [make_delete_task(3.0, 5.0)]
        segments = calculate_keep_segments(tasks, 10.0)

        assert len(segments) == 2
        assert segments[0].start == 0
        assert segments[0].end == 3.0
        assert segments[1].start == 5.0
        assert segments[1].end == 10.0

    def test_multiple_deletions(self):
        """多个删除任务"""
        tasks = [
            make_delete_task(2.0, 3.0),
            make_delete_task(5.0, 6.0),
            make_delete_task(8.0, 9.0),
        ]
        segments = calculate_keep_segments(tasks, 10.0)

        assert len(segments) == 4
        assert segments[0].end == 2.0
        assert segments[1].start == 3.0
        assert segments[1].end == 5.0

    def test_overlapping_deletions(self):
        """重叠的删除区间"""
        tasks = [
            make_delete_task(2.0, 5.0),
            make_delete_task(4.0, 6.0),  # 与上一个重叠
        ]
        segments = calculate_keep_segments(tasks, 10.0)

        # 应该合并为一个删除区间 2.0-6.0
        assert len(segments) == 2
        assert segments[0].end == 2.0
        assert segments[1].start == 6.0

    def test_deletion_at_start(self):
        """开头删除"""
        tasks = [make_delete_task(0.0, 2.0)]
        segments = calculate_keep_segments(tasks, 10.0)

        assert len(segments) == 1
        assert segments[0].start == 2.0
        assert segments[0].end == 10.0

    def test_deletion_at_end(self):
        """结尾删除"""
        tasks = [make_delete_task(8.0, 10.0)]
        segments = calculate_keep_segments(tasks, 10.0)

        assert len(segments) == 1
        assert segments[0].start == 0
        assert segments[0].end == 8.0

    def test_unsorted_tasks(self):
        """未排序的任务"""
        tasks = [
            make_delete_task(5.0, 6.0),
            make_delete_task(2.0, 3.0),  # 在前面
        ]
        segments = calculate_keep_segments(tasks, 10.0)

        # 应该正确排序后处理
        assert len(segments) == 3


class TestGenerateFFmpegFilter:
    """FFmpeg filter 生成测试"""

    def test_single_segment(self):
        """单个片段"""
        segments = [KeepSegment(0, 10.0)]
        filter_str = generate_ffmpeg_filter(segments)

        assert "trim" in filter_str
        assert "concat" in filter_str
        assert "n=1" in filter_str

    def test_multiple_segments(self):
        """多个片段"""
        segments = [
            KeepSegment(0, 3.0),
            KeepSegment(5.0, 8.0),
            KeepSegment(9.0, 10.0),
        ]
        filter_str = generate_ffmpeg_filter(segments)

        assert "n=3" in filter_str
        assert "[v0]" in filter_str
        assert "[v1]" in filter_str
        assert "[v2]" in filter_str

    def test_empty_segments(self):
        """空片段列表"""
        filter_str = generate_ffmpeg_filter([])

        assert filter_str == ""


class TestGetOutputPath:
    """输出路径生成测试"""

    def test_default_suffix(self):
        """默认后缀"""
        path = get_output_path("/path/to/video.mp4")

        assert Path(path) == Path("/path/to/video_cut.mp4")

    def test_custom_suffix(self):
        """自定义后缀"""
        path = get_output_path("/path/to/video.mp4", "_final")

        assert Path(path) == Path("/path/to/video_final.mp4")

    def test_different_extension(self):
        """不同扩展名"""
        path = get_output_path("/path/to/video.mov", "_cut")

        assert Path(path) == Path("/path/to/video_cut.mov")


class TestKeepSegment:
    """保留片段测试"""

    def test_duration(self):
        """时长计算"""
        seg = KeepSegment(1.5, 4.5)

        assert seg.duration == 3.0

    def test_zero_duration(self):
        """零时长"""
        seg = KeepSegment(1.0, 1.0)

        assert seg.duration == 0.0
