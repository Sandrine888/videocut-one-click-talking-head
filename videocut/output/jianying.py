"""
剪映输出模块

将视频推送到剪映草稿箱
"""

import os
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

from rich.console import Console

console = Console()

# 剪映草稿目录
JIANYING_DRAFT_PATHS = {
    "darwin": [  # macOS
        Path.home() / "Movies" / "JianyingPro Drafts",
        Path.home() / "Movies" / "CapCut" / "Drafts",
    ],
    "win32": [  # Windows
        Path.home() / "AppData" / "Local" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
        Path.home() / "Documents" / "CapCut" / "Drafts",
    ]
}


def find_jianying_draft_dir() -> Optional[Path]:
    """
    自动检测剪映草稿目录

    Returns:
        草稿目录路径，未找到返回 None
    """
    import sys
    platform = sys.platform

    paths = JIANYING_DRAFT_PATHS.get(platform, [])

    for path in paths:
        if path.exists():
            return path

    return None


def create_draft(
    video_path: str,
    draft_name: Optional[str] = None,
    draft_dir: Optional[str] = None
) -> Optional[str]:
    """
    创建剪映草稿

    Args:
        video_path: 视频文件路径
        draft_name: 草稿名称，默认使用视频文件名
        draft_dir: 草稿目录，默认自动检测

    Returns:
        草稿路径，失败返回 None
    """
    try:
        from pyJianYingDraft import JianYingDraft
    except ImportError:
        console.print("[red]错误: pyJianYingDraft 未安装[/red]")
        console.print("请运行: pip install pyJianYingDraft")
        return None

    video_path = Path(video_path)

    if not video_path.exists():
        console.print(f"[red]错误: 视频文件不存在 - {video_path}[/red]")
        return None

    # 确定草稿目录
    if draft_dir:
        target_dir = Path(draft_dir)
    else:
        target_dir = find_jianying_draft_dir()
        if not target_dir:
            console.print("[red]错误: 未找到剪映草稿目录[/red]")
            console.print("请手动指定草稿目录或确认剪映已安装")
            return None

    # 草稿名称
    if not draft_name:
        draft_name = video_path.stem + "_" + datetime.now().strftime("%H%M%S")

    console.print(f"⏳ 正在创建剪映草稿: {draft_name}")

    try:
        # 创建草稿
        draft = JianYingDraft(draft_name, target_dir)

        # 添加视频素材
        draft.add_video(str(video_path))

        # 保存草稿
        draft_path = draft.save()

        # 处理 draft_content.json -> draft_info.json 重命名问题
        # pyJianYingDraft 可能生成的是 draft_content.json
        # 但剪映需要 draft_info.json
        draft_folder = target_dir / draft_name
        content_file = draft_folder / "draft_content.json"
        info_file = draft_folder / "draft_info.json"

        if content_file.exists() and not info_file.exists():
            # 复制一份为 draft_info.json
            shutil.copy(content_file, info_file)
            console.print("[dim]已创建 draft_info.json[/dim]")

        console.print(f"[green]✓ 草稿已创建: {draft_path}[/green]")
        console.print("[cyan]请打开剪映查看草稿[/cyan]")

        return str(draft_path)

    except Exception as e:
        console.print(f"[red]创建草稿失败: {e}[/red]")
        return None


def push_to_jianying(
    video_path: str,
    srt_path: Optional[str] = None,
    draft_name: Optional[str] = None
) -> bool:
    """
    推送视频到剪映（简化接口）

    Args:
        video_path: 视频文件路径
        srt_path: SRT 字幕路径（可选，剪映会自动识别）
        draft_name: 草稿名称

    Returns:
        是否成功
    """
    result = create_draft(video_path, draft_name)
    return result is not None


def check_jianying_installed() -> bool:
    """检查剪映是否安装"""
    draft_dir = find_jianying_draft_dir()
    return draft_dir is not None


if __name__ == "__main__":
    # 测试
    draft_dir = find_jianying_draft_dir()
    if draft_dir:
        print(f"找到剪映草稿目录: {draft_dir}")
    else:
        print("未找到剪映草稿目录")
