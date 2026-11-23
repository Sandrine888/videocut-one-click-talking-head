"""
AI 文案重组模块

调用 LLM 分析转录文案，生成优化方案
"""

import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .transcribe import TranscriptResult
from .slip_detect import DeleteTask, SlipType
from .llm import get_llm_client

console = Console()


# Prompt 模板
REWRITE_PROMPT = """你是一位专业的视频文案编辑，擅长优化口播视频的文案结构。

## 任务
分析以下口播视频转录文本，找出需要删除的冗余内容，让视频更加流畅精炼。

## 转录文本
{transcript}

## 已识别的问题（自动检测）
{detected_issues}

## 要求
1. 分析文案结构，识别可以删除的冗余内容
2. 提供 2 个不同的优化方案：
   - 方案A：轻度优化（只删除明显冗余）
   - 方案B：深度优化（精简到核心内容）
3. 每个方案说明删除理由

## 输出格式（严格按JSON格式）
```json
{{
  "analysis": "文案整体分析（50字以内）",
  "plans": [
    {{
      "name": "A-轻度优化",
      "description": "优化思路说明",
      "deletions": [
        {{"text": "要删除的文字", "reason": "删除理由"}}
      ],
      "result_preview": "优化后的预览文案"
    }},
    {{
      "name": "B-深度优化",
      "description": "优化思路说明",
      "deletions": [
        {{"text": "要删除的文字", "reason": "删除理由"}}
      ],
      "result_preview": "优化后的预览文案"
    }}
  ]
}}
```

只输出JSON，不要其他内容。
"""


@dataclass
class RewritePlan:
    """重组方案"""
    name: str
    description: str
    deletions: List[Dict[str, str]]  # [{"text": "...", "reason": "..."}]
    result_preview: str


@dataclass
class RewriteResult:
    """重组结果"""
    analysis: str
    plans: List[RewritePlan]
    raw_response: str


def format_detected_issues(tasks: List[DeleteTask]) -> str:
    """格式化已检测的问题"""
    if not tasks:
        return "无"

    lines = []
    for task in tasks:
        if task.slip_type == SlipType.SILENCE:
            lines.append(f"- 静音 {task.duration:.1f}s")
        elif task.slip_type == SlipType.FILLER:
            lines.append(f"- 语气词「{task.text}」")
        else:
            lines.append(f"- {task.slip_type.value}「{task.text}」→ 保留「{task.keep_text}」")

    return "\n".join(lines)


def parse_llm_response(response: str) -> Optional[RewriteResult]:
    """解析 LLM 响应"""
    try:
        # 尝试提取 JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = response.strip()

        data = json.loads(json_str)

        plans = []
        for plan_data in data.get("plans", []):
            plans.append(RewritePlan(
                name=plan_data.get("name", ""),
                description=plan_data.get("description", ""),
                deletions=plan_data.get("deletions", []),
                result_preview=plan_data.get("result_preview", "")
            ))

        return RewriteResult(
            analysis=data.get("analysis", ""),
            plans=plans,
            raw_response=response
        )

    except (json.JSONDecodeError, KeyError) as e:
        console.print(f"[yellow]解析 AI 响应失败: {e}[/yellow]")
        return None


def analyze_transcript(
    transcript: TranscriptResult,
    detected_tasks: List[DeleteTask] = None
) -> Optional[RewriteResult]:
    """
    调用 AI 分析转录文案

    Args:
        transcript: 转录结果
        detected_tasks: 已检测的删除任务

    Returns:
        RewriteResult 或 None（失败时）
    """
    console.print("⏳ AI 正在分析文案...")

    try:
        client = get_llm_client()
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")
        return None

    # 构建 prompt
    detected_str = format_detected_issues(detected_tasks or [])
    prompt = REWRITE_PROMPT.format(
        transcript=transcript.full_text,
        detected_issues=detected_str
    )

    try:
        response = client.chat([
            {"role": "user", "content": prompt}
        ])

        result = parse_llm_response(response)

        if result:
            console.print("[green]✓ AI 分析完成[/green]")
            return result
        else:
            console.print("[yellow]AI 响应格式异常[/yellow]")
            return None

    except Exception as e:
        console.print(f"[red]AI 调用失败: {e}[/red]")
        return None


def display_rewrite_plans(result: RewriteResult):
    """显示重组方案"""
    # 显示分析
    console.print(Panel(result.analysis, title="📊 文案分析", border_style="cyan"))
    console.print()

    # 显示每个方案
    for i, plan in enumerate(result.plans):
        # 方案标题
        console.print(f"[bold cyan]{'='*50}[/bold cyan]")
        console.print(f"[bold]方案 {i+1}: {plan.name}[/bold]")
        console.print(f"[dim]{plan.description}[/dim]")
        console.print()

        # 删除列表
        if plan.deletions:
            table = Table(title="删除内容", show_header=True)
            table.add_column("删除文字", style="red")
            table.add_column("理由")

            for d in plan.deletions:
                table.add_row(d.get("text", ""), d.get("reason", ""))

            console.print(table)

        # 预览
        console.print()
        console.print(Panel(
            plan.result_preview,
            title="优化后预览",
            border_style="green"
        ))
        console.print()


def convert_plan_to_tasks(
    plan: RewritePlan,
    transcript: TranscriptResult
) -> List[DeleteTask]:
    """
    将重组方案转换为删除任务

    根据要删除的文字在转录结果中查找时间戳
    """
    tasks = []
    full_text = transcript.full_text
    chars = transcript.chars

    for deletion in plan.deletions:
        text = deletion.get("text", "")
        if not text:
            continue

        # 在全文中查找位置
        idx = full_text.find(text)
        if idx == -1:
            console.print(f"[yellow]警告: 未找到「{text}」[/yellow]")
            continue

        # 获取时间戳
        if idx < len(chars) and idx + len(text) <= len(chars):
            start = chars[idx].start
            end = chars[idx + len(text) - 1].end

            tasks.append(DeleteTask(
                slip_type=SlipType.REPLACE,  # AI 建议的删除
                start=start,
                end=end,
                text=text,
                context=deletion.get("reason", "AI建议删除"),
                keep_text=""
            ))

    return tasks


if __name__ == "__main__":
    # 测试
    from .transcribe import TranscriptResult, CharTimestamp

    test_chars = [
        CharTimestamp("你", 0.0, 0.2),
        CharTimestamp("好", 0.2, 0.4),
        CharTimestamp("嗯", 0.5, 0.7),
        CharTimestamp("今", 0.8, 1.0),
        CharTimestamp("天", 1.0, 1.2),
    ]

    test_result = TranscriptResult(
        video_file="test.mp4",
        full_text="你好嗯今天",
        duration=5.0,
        chars=test_chars
    )

    # 需要配置好 LLM 才能测试
    # result = analyze_transcript(test_result)
    # if result:
    #     display_rewrite_plans(result)
