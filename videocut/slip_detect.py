"""
口误识别模块

识别口误、语气词、长静音
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console
from rich.table import Table

from .transcribe import TranscriptResult, CharTimestamp

console = Console()


class SlipType(Enum):
    """口误类型"""
    REPEAT = "重复型"      # 如: 拉满新拉满
    REPLACE = "替换型"     # 如: AI就是AI就会
    STUTTER = "卡顿型"     # 如: 听会会
    FILLER = "语气词"      # 如: 嗯、啊
    SILENCE = "静音"       # 长静音 >= 1s


@dataclass
class DeleteTask:
    """删除任务"""
    slip_type: SlipType
    start: float          # 开始时间（秒）
    end: float            # 结束时间（秒）
    text: str             # 要删除的文本
    context: str          # 上下文
    keep_text: str = ""   # 保留的文本（口误时）
    confirmed: bool = True  # 是否确认删除

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)

    def to_markdown(self, index: int) -> str:
        """生成 Markdown 格式"""
        checkbox = "[x]" if self.confirmed else "[ ]"
        if self.slip_type == SlipType.SILENCE:
            return f"- {checkbox} {index}. `({self.start:.2f}-{self.end:.2f})` 静音 {self.duration:.1f}s"
        elif self.slip_type == SlipType.FILLER:
            return f"- {checkbox} {index}. `({self.start:.2f}-{self.end:.2f})` 删\"{self.text}\" 上下文: {self.context}"
        else:
            return f"- {checkbox} {index}. `({self.start:.2f}-{self.end:.2f})` 删\"{self.text}\" → 保留\"{self.keep_text}\""


@dataclass
class SlipDetectResult:
    """口误识别结果"""
    slips: List[DeleteTask] = field(default_factory=list)      # 口误
    fillers: List[DeleteTask] = field(default_factory=list)    # 语气词
    silences: List[DeleteTask] = field(default_factory=list)   # 静音

    @property
    def all_tasks(self) -> List[DeleteTask]:
        """所有删除任务"""
        return self.slips + self.fillers + self.silences

    @property
    def confirmed_tasks(self) -> List[DeleteTask]:
        """已确认的删除任务"""
        return [t for t in self.all_tasks if t.confirmed]

    def to_markdown(self) -> str:
        """生成 Markdown 格式的审查稿"""
        lines = ["# 删除任务清单\n"]

        if self.slips:
            lines.append(f"**口误（{len(self.slips)}处）**：")
            for i, task in enumerate(self.slips, 1):
                lines.append(task.to_markdown(i))
            lines.append("")

        if self.fillers:
            lines.append(f"**语气词（{len(self.fillers)}处）**：")
            for i, task in enumerate(self.fillers, 1):
                lines.append(task.to_markdown(i))
            lines.append("")

        if self.silences:
            lines.append(f"**静音（{len(self.silences)}处）**：")
            for i, task in enumerate(self.silences, 1):
                lines.append(task.to_markdown(i))

        return "\n".join(lines)

    def print_summary(self):
        """打印摘要"""
        table = Table(title="识别结果", show_header=True)
        table.add_column("类型", style="cyan")
        table.add_column("数量", justify="right")

        table.add_row("口误", str(len(self.slips)))
        table.add_row("语气词", str(len(self.fillers)))
        table.add_row("静音", str(len(self.silences)))
        table.add_row("总计", str(len(self.all_tasks)), style="bold")

        console.print(table)


# 语气词列表
FILLER_WORDS = ['嗯', '啊', '哎', '诶', '呃', '额', '唉', '哦', '噢', '呀', '欸', '嗯嗯']

# 合法叠词白名单（不应被识别为卡顿）
# 包含常见的 AABB 型、AA 型词汇
VALID_REPEATED_WORDS = {
    # 称谓类
    '谢谢', '哥哥', '姐姐', '弟弟', '妹妹', '爸爸', '妈妈', '爷爷', '奶奶',
    '叔叔', '阿姨', '姑姑', '舅舅', '婆婆', '公公', '娃娃', '宝宝', '乖乖',
    # 动作类
    '看看', '试试', '想想', '说说', '听听', '走走', '逛逛', '聊聊', '问问',
    '等等', '停停', '动动', '摸摸', '碰碰', '拍拍', '摇摇', '晃晃', '转转',
    # 状态类
    '常常', '往往', '刚刚', '偷偷', '悄悄', '慢慢', '渐渐', '静静', '轻轻',
    '深深', '淡淡', '暖暖', '冷冷', '甜甜', '酸酸', '苦苦', '辣辣',
    # 名词类
    '星星', '点点', '滴滴', '粒粒', '条条', '朵朵', '片片', '层层', '处处',
    # 其他常用
    '哈哈', '呵呵', '嘻嘻', '嘿嘿', '拜拜', '晚晚', '天天', '年年', '岁岁',
}


def detect_fillers(transcript: TranscriptResult) -> List[DeleteTask]:
    """
    检测语气词

    删除边界：从前一个字的 end 到后一个字的 start
    """
    tasks = []
    chars = transcript.chars

    for i, char in enumerate(chars):
        if char.char in FILLER_WORDS:
            # 获取上下文
            prev_char = chars[i - 1] if i > 0 else None
            next_char = chars[i + 1] if i < len(chars) - 1 else None

            # 计算删除边界
            start = prev_char.end if prev_char else char.start
            end = next_char.start if next_char else char.end

            # 上下文显示
            prev_text = prev_char.char if prev_char else ""
            next_text = next_char.char if next_char else ""
            context = f"{prev_text}【{char.char}】{next_text}"

            tasks.append(DeleteTask(
                slip_type=SlipType.FILLER,
                start=start,
                end=end,
                text=char.char,
                context=context
            ))

    return tasks


def detect_silences(transcript: TranscriptResult, threshold: float = 1.0) -> List[DeleteTask]:
    """
    检测长静音

    Args:
        transcript: 转录结果
        threshold: 静音阈值（秒），默认 1.0

    Returns:
        静音删除任务列表
    """
    tasks = []
    chars = transcript.chars

    # 检测开头静音
    if chars and chars[0].start > threshold:
        tasks.append(DeleteTask(
            slip_type=SlipType.SILENCE,
            start=0,
            end=chars[0].start,
            text="",
            context="开头静音"
        ))

    # 检测句间静音
    for i in range(len(chars) - 1):
        gap = chars[i + 1].start - chars[i].end
        if gap >= threshold:
            tasks.append(DeleteTask(
                slip_type=SlipType.SILENCE,
                start=chars[i].end,
                end=chars[i + 1].start,
                text="",
                context=f"{chars[i].char}...{chars[i+1].char}"
            ))

    return tasks


def detect_slips_simple(transcript: TranscriptResult) -> List[DeleteTask]:
    """
    简单口误检测

    基于文本重复模式检测，适合快速处理

    TODO: 后续可以用 LLM 做更智能的检测
    """
    tasks = []
    text = transcript.full_text
    chars = transcript.chars

    # 检测连续重复字（卡顿型）
    # 如: "听会会" -> 删第一个"会"
    # 但跳过合法叠词如"谢谢"、"看看"
    i = 0
    while i < len(text) - 1:
        if text[i] == text[i + 1]:
            # 找到重复
            j = i + 1
            while j < len(text) and text[j] == text[i]:
                j += 1

            repeat_count = j - i
            repeated_text = text[i:j]

            # 检查是否为合法叠词（仅两个相同字符的情况）
            if repeat_count == 2 and repeated_text in VALID_REPEATED_WORDS:
                # 是合法叠词，跳过
                i = j
                continue

            # 只保留最后一个（对于真正的卡顿）
            if repeat_count >= 2:
                tasks.append(DeleteTask(
                    slip_type=SlipType.STUTTER,
                    start=chars[i].start,
                    end=chars[j - 2].end,
                    text=text[i:j-1],
                    context=text[max(0, i-2):min(len(text), j+2)],
                    keep_text=text[j-1]
                ))
            i = j
        else:
            i += 1

    # 检测短语重复（重复型）
    # 简单实现：检测 2-4 字的重复
    for length in range(2, 5):
        i = 0
        while i < len(text) - length * 2:
            phrase = text[i:i + length]
            next_phrase = text[i + length:i + length * 2]

            if phrase == next_phrase:
                # 找到重复，删第一个
                start_idx = i
                end_idx = i + length

                tasks.append(DeleteTask(
                    slip_type=SlipType.REPEAT,
                    start=chars[start_idx].start,
                    end=chars[end_idx - 1].end,
                    text=phrase,
                    context=text[max(0, i-2):min(len(text), i+length*2+2)],
                    keep_text=phrase
                ))

                i += length * 2  # 跳过重复部分
            else:
                i += 1

    return tasks


def detect_all(transcript: TranscriptResult) -> SlipDetectResult:
    """
    执行完整的口误识别

    Returns:
        SlipDetectResult 包含所有检测结果
    """
    console.print("⏳ 正在识别口误...")

    # 检测各类问题
    slips = detect_slips_simple(transcript)
    console.print(f"  口误: {len(slips)}处")

    fillers = detect_fillers(transcript)
    console.print(f"  语气词: {len(fillers)}处")

    silences = detect_silences(transcript)
    console.print(f"  静音: {len(silences)}处")

    result = SlipDetectResult(
        slips=slips,
        fillers=fillers,
        silences=silences
    )

    console.print(f"[green]✓ 识别完成，共 {len(result.all_tasks)} 处需要处理[/green]")

    return result


if __name__ == "__main__":
    # 测试
    from .transcribe import TranscriptResult

    # 模拟数据
    test_chars = [
        CharTimestamp("你", 1.0, 1.2),
        CharTimestamp("好", 1.2, 1.4),
        CharTimestamp("嗯", 2.0, 2.2),  # 语气词
        CharTimestamp("我", 2.5, 2.7),
        CharTimestamp("是", 2.7, 2.9),
        CharTimestamp("是", 2.9, 3.1),  # 卡顿
        CharTimestamp("测", 3.1, 3.3),
        CharTimestamp("试", 3.3, 3.5),
    ]

    test_result = TranscriptResult(
        video_file="test.mp4",
        full_text="你好嗯我是是测试",
        duration=10.0,
        chars=test_chars
    )

    result = detect_all(test_result)
    print("\n" + result.to_markdown())
