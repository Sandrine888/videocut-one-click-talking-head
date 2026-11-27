"""D 模块 · 基础动效（PRD.md v1.0）

功能：字幕淡入（80–150ms）、每条最多 1 个重点词高亮、章节角标、
「无动效/轻动效」对照样片、逐帧几何自检。

技术路线（已定死，见 PRD 2.2）：
    pysubs2 生成 ASS 特效标签 -> ffmpeg 内置 libass 单次烧录（-c:a copy，不改时长）。

边界：只读 A 的模板配置；不改 C 的断句文本；不碰 B/E 的文件。
独立运行：python -m videocut.render.effects --demo

跨模块接口契约（与 A/B/C/E 配对用，详见 docs/D模块_接口契约.md）
------------------------------------------------------------------
输入（均为 JSON 可序列化对象；时间单位：字幕/章节一律「秒(float, s)」，淡入「毫秒(int, ms)」）：
  segments : List[Dict]  必填。C 的字幕片段，每条字段：
      index : int   可选，缺省按 1 起序号补齐
      start : float 必填，秒，>= 0
      end   : float 必填，秒，> start
      text  : str   必填，非空；C 断句后的最终文本，D 不改内容
  template : Dict | str 必填。A 的模板配置 dict 或 JSON 文件路径；
      缺字段自动用 DEFAULT_TEMPLATE 补齐；effects.fade_in_ms 单位 ms，越界钳制 80–150
  chapters : List[Dict] | None 可选。章节切换点，每条字段：
      start : float 必填，秒，>= 0，整体按 start 单调递增
      label : str   必填，非空；None/[] 表示不加角标
  video    : str | Path 必填（仅 render / render_pair / burn）。原片路径，须存在。
输出：
  render_ass(segments, template, chapters, ...) -> str   ASS 字幕文件路径
  render(video, segments, template, chapters, ...) -> RenderResult
      字段：orientation / ass_light / ass_noeffects / mp4_light / mp4_noeffects
            / report_path / checks（挡脸/贴边/超两行违规计数），可 .to_dict()
错误处理（全部继承 EffectsError；CLI 退出码 2）：
  InputError  (ValueError)  字段缺失/类型错/时间非法/配置非法
  MediaError  (RuntimeError) 视频不存在、ffprobe 读不出分辨率或时长
  RenderError (RuntimeError) ffmpeg 烧录失败（消息含 stderr 尾部）
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pysubs2


# ---------------------------------------------------------------------------
# 0. 接口错误类型（跨模块配对用，见模块 docstring 契约）
# ---------------------------------------------------------------------------

class EffectsError(Exception):
    """D 模块错误基类。"""


class InputError(EffectsError, ValueError):
    """输入字段缺失、类型错误、时间非法（start>=end、负数、空列表）、配置非法。"""


class MediaError(EffectsError, RuntimeError):
    """视频文件不存在，或 ffprobe 读不出分辨率/时长。"""


class RenderError(EffectsError, RuntimeError):
    """ffmpeg 烧录失败、ASS 落盘失败（消息含 stderr 尾部）。"""


def _num(value, name: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{where} 的 {name} 必须是数字（秒），收到 {type(value).__name__}: {value!r}")
    return float(value)


def validate_segments(segments) -> List[Dict]:
    """校验并规范化 segments（补 index、时间转 float 秒）。非法时抛 InputError。"""
    if not isinstance(segments, (list, tuple)) or not segments:
        raise InputError("segments 必须是非空列表")
    out: List[Dict] = []
    for i, seg in enumerate(segments, 1):
        where = f"segments[{i - 1}]"
        if not isinstance(seg, dict):
            raise InputError(f"{where} 必须是对象(dict)，收到 {type(seg).__name__}")
        for key in ("start", "end", "text"):
            if key not in seg:
                raise InputError(f"{where} 缺少必填字段 {key!r}")
        start = _num(seg["start"], "start", where)
        end = _num(seg["end"], "end", where)
        if start < 0:
            raise InputError(f"{where}.start 不能为负: {start}")
        if end <= start:
            raise InputError(f"{where} 需要 end > start，收到 start={start} end={end}")
        if not isinstance(seg["text"], str) or not seg["text"].strip():
            raise InputError(f"{where}.text 必须是非空字符串")
        index = seg.get("index", i)
        if not isinstance(index, int) or isinstance(index, bool):
            raise InputError(f"{where}.index 必须是整数，收到 {index!r}")
        out.append({"index": index, "start": start, "end": end, "text": seg["text"].strip()})
    return out


def validate_chapters(chapters) -> List[Dict]:
    """校验并规范化 chapters（None/[] 合法=不加角标）。非法时抛 InputError。"""
    if chapters is None:
        return []
    if not isinstance(chapters, (list, tuple)):
        raise InputError(f"chapters 必须是列表或 None，收到 {type(chapters).__name__}")
    out: List[Dict] = []
    for i, ch in enumerate(chapters):
        where = f"chapters[{i}]"
        if not isinstance(ch, dict):
            raise InputError(f"{where} 必须是对象(dict)，收到 {type(ch).__name__}")
        for key in ("start", "label"):
            if key not in ch:
                raise InputError(f"{where} 缺少必填字段 {key!r}")
        start = _num(ch["start"], "start", where)
        if start < 0:
            raise InputError(f"{where}.start 不能为负: {start}")
        if not isinstance(ch["label"], str) or not ch["label"].strip():
            raise InputError(f"{where}.label 必须是非空字符串")
        out.append({"start": start, "label": ch["label"].strip()})
    for a, b in zip(out, out[1:]):
        if b["start"] <= a["start"]:
            raise InputError(f"chapters 必须按 start 严格递增: {a['start']} -> {b['start']}")
    return out


# ---------------------------------------------------------------------------
# 默认数据（PRD 3.1：v1 用自造样例，字段约定即内部接口）
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE: Dict = {
    "orientation": "portrait",
    "chars_per_line": {"portrait": [12, 16], "landscape": [16, 22]},
    "max_lines": 2,
    "safe_area": {"left_pct": 8, "right_pct": 8, "bottom_pct": 15},
    "font": {"name": "Microsoft YaHei", "size_portrait": 48, "size_landscape": 36},
    "colors": {
        "primary": "&H00FFFFFF",
        "outline": "&H00000000",
        "highlight": "&H0000FFFF",
    },
    "effects": {
        "fade_in_ms": 120,
        "highlight_max_per_segment": 1,
        "badge": {"enabled": True, "position": "top_right", "shrink_when_speaking": True},
    },
}

# v1 内置样例术语表（正式术语表归 C 维护，这里仅供 demo 与选词规则使用）
SAMPLE_GLOSSARY: List[str] = [
    "FunASR", "VideoCut", "FFmpeg", "OpenAI", "Claude", "GPT",
    "API", "SRT", "ASS", "MP4", "H.264", "AAC", "Whisper",
    "ASR", "LLM",
]

DEMO_SEGMENTS: List[Dict] = [
    {"index": 1, "start": 0.5, "end": 3.0, "text": "大家好，欢迎来到我的频道。"},
    {"index": 2, "start": 3.2, "end": 6.0, "text": "今天聊聊 FunASR 的用法。"},
    {"index": 3, "start": 6.5, "end": 9.0, "text": "这个功能提升了 30% 的效率。"},
    {"index": 4, "start": 9.2, "end": 11.5, "text": "我们下期再见。"},
]

DEMO_CHAPTERS: List[Dict] = [
    {"start": 0.0, "label": "开场"},
    {"start": 6.5, "label": "第2节 · 实操"},
]

PLAY_RES = {"portrait": (1080, 1920), "landscape": (1920, 1080)}

FADE_MIN_MS, FADE_MAX_MS = 80, 150


# ---------------------------------------------------------------------------
# 1. load_template
# ---------------------------------------------------------------------------

def _deep_merge(base: Dict, override: Dict) -> Dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_template(path: Optional[Union[str, Dict]] = None) -> Dict:
    """读配置、校验区间、缺字段用默认值补齐。fade_in_ms 越界钳制到 80–150。

    参数可为 JSON 文件路径、已解析的 dict，或 None（全默认）。
    配置非法时抛 InputError。
    """
    user: Dict = {}
    if isinstance(path, dict):
        user = copy.deepcopy(path)
    elif path:
        p = Path(path)
        if not p.exists():
            raise InputError(f"模板配置 JSON 文件不存在: {path}")
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InputError(f"模板配置 JSON 解析失败: {path}: {e}") from e
        if not isinstance(user, dict):
            raise InputError(f"模板配置必须是 JSON 对象，收到 {type(user).__name__}")
    tpl = _deep_merge(DEFAULT_TEMPLATE, user)

    if not isinstance(tpl["orientation"], str) or tpl["orientation"] not in PLAY_RES:
        raise InputError(f"orientation 必须是 portrait/landscape，收到 {tpl['orientation']!r}")
    fade = tpl["effects"]["fade_in_ms"]
    if isinstance(fade, bool) or not isinstance(fade, (int, float)):
        raise InputError(f"effects.fade_in_ms 必须是毫秒数(int, ms)，收到 {fade!r}")
    if not (FADE_MIN_MS <= fade <= FADE_MAX_MS):
        clamped = max(FADE_MIN_MS, min(FADE_MAX_MS, fade))
        print(f"[effects] 警告: fade_in_ms={fade} 越界，钳制为 {clamped}")
        tpl["effects"]["fade_in_ms"] = int(clamped)
    for orient in ("portrait", "landscape"):
        cpl = tpl["chars_per_line"].get(orient)
        if not (isinstance(cpl, list) and len(cpl) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in cpl)):
            raise InputError(f"chars_per_line.{orient} 必须是 2 个整数的列表，收到 {cpl!r}")
    return tpl


# ---------------------------------------------------------------------------
# 2. pick_highlight_word（PRD F2：术语 -> 数字 -> 不高亮，每条最多 1 个）
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")


def pick_highlight_word(text: str, glossary: Optional[List[str]] = None) -> Optional[str]:
    """返回文本中应高亮的词；无命中返回 None。规则机械可验证。"""
    glossary = SAMPLE_GLOSSARY if glossary is None else glossary
    best: Optional[Tuple[int, int, str]] = None  # (pos, -len, word)
    for term in glossary:
        pos = text.find(term)
        if pos >= 0:
            key = (pos, -len(term))
            if best is None or key < (best[0], best[1]):
                best = (pos, -len(term), term)
    if best:
        return best[2]
    m = _NUM_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# 文本折行与宽度估算（几何自检用）
# ---------------------------------------------------------------------------

def wrap_text(text: str, max_chars: int) -> List[str]:
    """按每行最大字数贪心折行（含标点计数）。"""
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines or [""]


def _est_line_width(line: str, fs: float) -> float:
    """保守估算行宽：CJK 全角=fs，ASCII≈0.55fs。"""
    return sum(fs if ord(c) > 0x2E80 else fs * 0.55 for c in line)


def _inline_color(style_color: str) -> str:
    """ASS 样式色 &HAABBGGRR -> 内联 \\c 用的 &HBBGGRR&。"""
    s = style_color.replace("&H", "").replace("&", "")
    if len(s) == 8:
        s = s[2:]
    return f"&H{s}&"


# ---------------------------------------------------------------------------
# 3. build_ass（核心：同一输入，effects_on 开关决定有无特效标签）
# ---------------------------------------------------------------------------

def build_ass(
    segments: List[Dict],
    template: Dict,
    chapters: Optional[List[Dict]] = None,
    effects_on: bool = True,
) -> pysubs2.SSAFile:
    """核心：同一份输入，effects_on 开关决定有无特效标签。

    输入校验见模块 docstring 契约；非法输入抛 InputError。
    """
    segments = validate_segments(segments)
    chapters = validate_chapters(chapters)
    if not isinstance(template, dict):
        raise InputError(f"template 必须是 dict（可先经 load_template 补齐），收到 {type(template).__name__}")
    orient = template["orientation"]
    w, h = PLAY_RES[orient]
    fs = template["font"]["size_portrait" if orient == "portrait" else "size_landscape"]
    max_chars = template["chars_per_line"][orient][1]
    safe = template["safe_area"]
    margin_lr = int(w * safe["left_pct"] / 100)
    margin_v = int(h * safe["bottom_pct"] / 100)
    colors = template["colors"]
    fade_ms = template["effects"]["fade_in_ms"]
    hl_inline = _inline_color(colors["highlight"])
    pr_inline = _inline_color(colors["primary"])

    subs = pysubs2.SSAFile()
    subs.info["Title"] = "videocut D-module effects"
    subs.info["PlayResX"] = str(w)
    subs.info["PlayResY"] = str(h)
    subs.info["WrapStyle"] = "2"  # 不自动折行，只认 \N
    subs.info["ScaledBorderAndShadow"] = "yes"

    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname=template["font"]["name"],
        fontsize=fs,
        primarycolor=colors["primary"],
        secondarycolor=colors["primary"],
        outlinecolor=colors["outline"],
        backcolor="&H80000000",
        bold=False,
        borderstyle=1,
        outline=2,
        shadow=0,
        alignment=pysubs2.Alignment.BOTTOM_CENTER,  # 底部居中
        marginl=margin_lr,
        marginr=margin_lr,
        marginv=margin_v,
        encoding=1,
    )

    # ---- 字幕事件 ----
    for seg in segments:
        text = seg["text"]
        lines = wrap_text(text, max_chars)
        hl_word = pick_highlight_word(text) if effects_on else None

        rendered_lines = []
        idx = 0
        for line in lines:
            start_idx, end_idx = idx, idx + len(line)
            idx = end_idx
            if hl_word:
                hp = text.find(hl_word)
                he = hp + len(hl_word)
                if hp < end_idx and he > start_idx:
                    a, b = max(hp, start_idx) - start_idx, min(he, end_idx) - start_idx
                    line = (
                        line[:a]
                        + "{\\c" + hl_inline + "}"
                        + line[a:b]
                        + "{\\c" + pr_inline + "}"
                        + line[b:]
                    )
            rendered_lines.append(line)

        body = "\\N".join(rendered_lines)
        if effects_on:
            body = "{\\fad(%d,0)}" % fade_ms + body
        subs.append(pysubs2.SSAEvent(
            start=pysubs2.make_time(s=seg["start"]),
            end=pysubs2.make_time(s=seg["end"]),
            text=body,
            style="Default",
            layer=0,
        ))

    # ---- 章节角标事件（仅轻动效版；PRD F3）----
    badge_cfg = template["effects"]["badge"]
    if effects_on and badge_cfg.get("enabled", True) and chapters:
        badge_fs = int(fs * 0.55)
        badge_margin_top = int(h * 0.06)
        pos_x = w - margin_lr  # 右上角，锚点在安全区内
        subs.styles["Badge"] = pysubs2.SSAStyle(
            fontname=template["font"]["name"],
            fontsize=badge_fs,
            primarycolor=colors["primary"],
            outlinecolor=colors["outline"],
            backcolor="&H80000000",
            borderstyle=1,
            outline=2,
            shadow=0,
            alignment=pysubs2.Alignment.TOP_RIGHT,  # 右上锚点
            marginl=margin_lr,
            marginr=margin_lr,
            marginv=badge_margin_top,
            encoding=1,
        )
        last_end = max((s["end"] for s in segments), default=0.0)
        for i, ch in enumerate(chapters):
            c_start = ch["start"]
            c_end = chapters[i + 1]["start"] if i + 1 < len(chapters) else last_end
            if c_end <= c_start:
                continue
            speaking = any(
                s["start"] < c_end and s["end"] > c_start for s in segments
            )
            tag = "{\\pos(%d,%d)}" % (pos_x, badge_margin_top)
            if speaking and badge_cfg.get("shrink_when_speaking", True):
                tag += "{\\fs%d\\1a&H80&}" % int(badge_fs * 0.6)
            subs.append(pysubs2.SSAEvent(
                start=pysubs2.make_time(s=c_start),
                end=pysubs2.make_time(s=c_end),
                text=tag + ch["label"],
                style="Badge",
                layer=1,
            ))
    return subs


def render_fullscreen_card(*args, **kwargs):
    """全屏章节卡：v1 刻意不做，仅留接口占位（PRD F3 / 第5节）。v2 可选。"""
    raise NotImplementedError("全屏卡不在 v1 范围，见 PRD.md 第5节")


# ---------------------------------------------------------------------------
# 4. burn（ffmpeg + libass 单次烧录，音频 copy，不改时长）
# ---------------------------------------------------------------------------

def _escape_filter_path(path: str) -> str:
    p = Path(path).as_posix()
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def burn(video: str, ass_path: str, out_path: str) -> bool:
    """ffmpeg + libass 单次烧录，-c:a copy 不改时长。失败抛 RenderError（含 stderr 尾部）。"""
    if not Path(video).exists():
        raise MediaError(f"视频文件不存在: {video}")
    if not Path(ass_path).exists():
        raise InputError(f"ASS 字幕文件不存在: {ass_path}")
    vf = "ass='%s'" % _escape_filter_path(ass_path)
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RenderError(f"FFmpeg 烧录失败 (exit {result.returncode}): {result.stderr[-800:]}")
    return True


# ---------------------------------------------------------------------------
# 5. render_pair（无动效/轻动效对照，时间轴逐条一致）
# ---------------------------------------------------------------------------

def render_pair(
    video: str,
    segments: List[Dict],
    template: Dict,
    chapters: Optional[List[Dict]],
    out_dir: str,
) -> Dict:
    """一键出「无动效/轻动效」两版成片 + 两份 ASS。返回 {"noeffects": {...}, "light": {...}}。"""
    if not Path(video).exists():
        raise MediaError(f"视频文件不存在: {video}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(video).stem
    paths = {}
    for key, effects_on in (("noeffects", False), ("light", True)):
        ass_path = out / f"{stem}_{key}.ass"
        mp4_path = out / f"{stem}_{key}.mp4"
        subs = build_ass(segments, template, chapters, effects_on=effects_on)
        try:
            subs.save(str(ass_path), encoding="utf-8")
        except OSError as e:
            raise RenderError(f"ASS 写入失败: {ass_path}: {e}") from e
        burn(video, str(ass_path), str(mp4_path))
        paths[key] = {"ass": str(ass_path), "mp4": str(mp4_path)}
    return paths


# ---------------------------------------------------------------------------
# 5b. 跨模块配对入口（接口契约，见模块 docstring 与 docs/D模块_接口契约.md）
# ---------------------------------------------------------------------------

def render_ass(
    segments: List[Dict],
    template: Union[str, Dict, None] = None,
    chapters: Optional[List[Dict]] = None,
    out_path: Optional[str] = None,
    effects_on: bool = True,
) -> str:
    """只生成 ASS 字幕、不碰视频。返回 ASS 文件路径（str）。

    template 可为 None（全默认）、dict 或 JSON 路径；非法输入抛 InputError，
    落盘失败抛 RenderError。
    """
    tpl = load_template(template)
    subs = build_ass(segments, tpl, chapters, effects_on=effects_on)
    if out_path is None:
        name = "light.ass" if effects_on else "noeffects.ass"
        out_path = str(Path("effects_output") / name)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        subs.save(str(p), encoding="utf-8")
    except OSError as e:
        raise RenderError(f"ASS 写入失败: {p}: {e}") from e
    return str(p)


@dataclass
class RenderResult:
    """render() 的渲染结果对象（字段全部可 JSON 序列化）。"""

    orientation: str                      # portrait / landscape
    video: str                            # 输入原片路径
    ass_light: str                        # 轻动效 ASS 路径
    ass_noeffects: str                    # 无动效 ASS 路径
    mp4_light: str                        # 轻动效成片路径
    mp4_noeffects: str                    # 无动效成片路径
    report_path: Optional[str] = None     # 自检报告 JSON（run_check=False 时为 None）
    checks: Dict[str, int] = field(default_factory=dict)  # face_block/edge_touch/over_two_lines 违规数

    @property
    def ok(self) -> bool:
        return not any(self.checks.values())

    def to_dict(self) -> Dict:
        return asdict(self)


def render(
    video: str,
    segments: List[Dict],
    template: Union[str, Dict, None] = None,
    chapters: Optional[List[Dict]] = None,
    out_dir: str = "effects_output",
    orientation: str = "auto",
    run_check: bool = True,
) -> RenderResult:
    """顶层配对入口：视频路径 + segments/template/chapters -> RenderResult。

    orientation="auto" 时按视频宽高判定并覆盖 template.orientation。
    错误：InputError（输入非法）/ MediaError（视频缺失或读不出分辨率）/
    RenderError（烧录、落盘失败）。
    """
    if orientation not in ("auto", "portrait", "landscape"):
        raise InputError(f"orientation 必须是 auto/portrait/landscape，收到 {orientation!r}")
    if not Path(video).exists():
        raise MediaError(f"视频文件不存在: {video}")
    tpl = load_template(template)
    if orientation == "auto":
        tpl["orientation"] = detect_orientation(video)
    elif orientation in ("portrait", "landscape"):
        tpl["orientation"] = orientation
    if chapters is None:
        chapters = auto_chapters(validate_segments(segments))
    paths = render_pair(video, segments, tpl, chapters, out_dir)
    report_path = str(Path(out_dir) / "check_report.json")
    checks: Dict[str, int] = {}
    if run_check:
        report = check_frames(paths["light"]["mp4"], paths["light"]["ass"], tpl, report_path)
        checks = report["checks"]
    return RenderResult(
        orientation=tpl["orientation"],
        video=str(video),
        ass_light=paths["light"]["ass"],
        ass_noeffects=paths["noeffects"]["ass"],
        mp4_light=paths["light"]["mp4"],
        mp4_noeffects=paths["noeffects"]["mp4"],
        report_path=report_path if run_check else None,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# 6. check_frames（抽帧 + 几何自检；PRD F5，不引入人脸检测模型）
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"\{[^}]*\}")
_FS_RE = re.compile(r"\\fs(\d+)")
_POS_RE = re.compile(r"\\pos\(([\d.]+),([\d.]+)\)")
_FAD_RE = re.compile(r"\\fad\((\d+),(\d+)\)")


def _ffprobe_duration(video: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def ffprobe_size(video: str) -> Tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    nums = re.findall(r"\d+", r.stdout)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    return 0, 0


def detect_orientation(video: str) -> str:
    w, h = ffprobe_size(video)
    if not w or not h:
        raise MediaError(f"无法读取视频分辨率（ffprobe 失败或文件不存在）: {video}")
    return "landscape" if w >= h else "portrait"


def segments_from_srt(path: str) -> List[Dict]:
    """SRT -> segments（时间换算为秒 float）。文件缺失/解析失败抛 InputError。"""
    if not Path(path).exists():
        raise InputError(f"字幕文件不存在: {path}")
    try:
        subs = pysubs2.load(str(path), encoding="utf-8")
    except Exception as e:
        raise InputError(f"SRT 解析失败: {path}: {e}") from e
    return [
        {"index": i + 1, "start": e.start / 1000.0, "end": e.end / 1000.0,
         "text": e.text.replace("\n", " ").strip()}
        for i, e in enumerate(subs) if e.text.strip()
    ]


def auto_chapters(segments: List[Dict], min_s: float = 12.0) -> List[Dict]:
    """按累计口播时长切章节，章节点对齐到某条字幕的起点（角标不跳在半句中间）。"""
    chapters, cur_start, acc = [], 0.0, 0.0
    for i, seg in enumerate(segments):
        if i and acc >= min_s:
            chapters.append({"start": seg["start"], "label": f"第{len(chapters) + 1}节"})
            acc = 0.0
        acc += seg["end"] - seg["start"]
    if chapters:
        chapters.insert(0, {"start": 0.0, "label": "开场"})
    return chapters


def _event_geometry(event, style, w: int, h: int, template: Dict) -> Dict:
    """从 ASS 事件推算渲染包围盒（保守估算）。"""
    raw = event.text
    plain = _TAG_RE.sub("", raw)
    lines = plain.split("\\N")
    fs = float(style.fontsize)
    m = _FS_RE.search(raw)
    if m:
        fs = float(m.group(1))
    line_h = fs * 1.25
    box_h = line_h * len(lines)
    box_w = max(_est_line_width(ln, fs) for ln in lines)

    pos = _POS_RE.search(raw)
    if pos:  # 角标：右上锚点
        x1, y0 = float(pos.group(1)), float(pos.group(2))
        x0, y1 = x1 - box_w, y0 + box_h
    else:  # 字幕：底部居中
        x0 = (w - box_w) / 2
        x1 = x0 + box_w
        y1 = h - style.marginv
        y0 = y1 - box_h
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "lines": len(lines), "fs": fs, "plain": plain}


def check_frames(
    video: str,
    ass_path: str,
    template: Dict,
    report_path: str,
) -> Dict:
    orient = template["orientation"]
    w, h = PLAY_RES[orient]
    safe = template["safe_area"]
    left, right = w * safe["left_pct"] / 100, w * (100 - safe["right_pct"]) / 100
    bottom = h * (100 - safe["bottom_pct"]) / 100
    max_lines = template["max_lines"]
    # 人脸保守区：画面中央 50% 宽 × 上半 60% 高（PRD F5）
    face = (w * 0.25, 0.0, w * 0.75, h * 0.6)
    tol = 1.0  # 像素容差

    subs = pysubs2.load(str(ass_path), encoding="utf-8")
    duration = _ffprobe_duration(video)

    violations: List[Dict] = []
    fade_vals: List[int] = []
    hl_counts: List[int] = []
    timestamps: List[float] = []
    fade_ms = template["effects"]["fade_in_ms"]

    for ev in subs:
        style = subs.styles[ev.style]
        t0, t1 = ev.start / 1000.0, ev.end / 1000.0
        geo = _event_geometry(ev, style, w, h, template)
        is_badge = ev.style == "Badge"

        for fad in _FAD_RE.finditer(ev.text):
            fade_vals.append(int(fad.group(1)))
        if not is_badge:
            hl_counts.append(ev.text.count("{\\c" + _inline_color(template["colors"]["highlight"]) + "}"))

        # 贴边
        if geo["x0"] < left - tol or geo["x1"] > right + tol or (not is_badge and geo["y1"] > bottom + tol):
            violations.append({"t": round(t0, 3), "kind": "edge_touch",
                               "detail": f"{ev.style} bbox=({geo['x0']:.0f},{geo['y0']:.0f})-({geo['x1']:.0f},{geo['y1']:.0f})"})
        # 超两行
        if geo["lines"] > max_lines:
            violations.append({"t": round(t0, 3), "kind": "over_two_lines",
                               "detail": f"{geo['lines']} 行: {geo['plain'][:30]}"})
        # 挡脸（角标侵入人脸保守区）
        if is_badge:
            fx0, fy0, fx1, fy1 = face
            if geo["x0"] < fx1 and geo["x1"] > fx0 and geo["y0"] < fy1 and geo["y1"] > fy0:
                violations.append({"t": round(t0, 3), "kind": "face_block",
                                   "detail": f"角标 bbox 与人脸区重叠: {geo['plain']}"})

        # 抽帧时间点：start / start+淡入 / end 附近 + 角标切换点
        timestamps += [t0 + 0.02, min(t0 + fade_ms / 1000.0, t1 - 0.02), t1 - 0.02]

    # 1fps 兜底
    if duration > 0:
        timestamps += [i + 0.5 for i in range(int(duration))]
    timestamps = sorted({round(min(max(t, 0.0), max(duration - 0.05, 0.0)), 3)
                         for t in timestamps if t >= 0})

    report_dir = Path(report_path).parent
    frame_dir = report_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    for i, t in enumerate(timestamps):
        fp = frame_dir / f"f_{i:04d}_{t:.3f}s.png"
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", str(fp)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and fp.exists():
            extracted += 1

    counts = {k: sum(1 for v in violations if v["kind"] == k)
              for k in ("face_block", "edge_touch", "over_two_lines")}
    rel = lambda p: os.path.relpath(str(p), str(report_dir)).replace(os.sep, "/")
    report = {
        "video": rel(video),
        "ass": rel(ass_path),
        "orientation": orient,
        "play_res": [w, h],
        "duration_s": round(duration, 3),
        "frames_extracted": extracted,
        "frame_dir": rel(frame_dir),
        "checks": counts,
        "violations": violations,
        "fade": {"count": len(fade_vals),
                 "min_ms": min(fade_vals) if fade_vals else None,
                 "max_ms": max(fade_vals) if fade_vals else None},
        "highlight": {"total_segments": len(hl_counts),
                      "max_per_segment": max(hl_counts) if hl_counts else 0,
                      "segments_with_highlight": sum(1 for c in hl_counts if c > 0)},
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


# ---------------------------------------------------------------------------
# demo：独立跑通 F1–F6（不依赖 A/B/C/E）
# ---------------------------------------------------------------------------

def _make_test_video(path: Path, orient: str, seconds: int = 12) -> None:
    w, h = PLAY_RES[orient]
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x336699:s={w}x{h}:d={seconds}:r=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("测试片生成失败:\n" + r.stderr[-500:])


def run_demo(out_dir: str = "demo_output") -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for orient in ("portrait", "landscape"):
        print(f"\n===== demo: {orient} =====")
        video = out / f"test_{orient}.mp4"
        if not video.exists():
            _make_test_video(video, orient)
        tpl = load_template()
        tpl["orientation"] = orient
        paths = render_pair(str(video), DEMO_SEGMENTS, tpl, DEMO_CHAPTERS, str(out / orient))
        report = check_frames(
            str(paths["light"]["mp4"]), paths["light"]["ass"], tpl,
            str(out / orient / "check_report.json"),
        )
        print(f"  无动效版: {paths['noeffects']['mp4']}")
        print(f"  轻动效版: {paths['light']['mp4']}")
        print(f"  抽帧 {report['frames_extracted']} 张 -> {report['frame_dir']}")
        print(f"  自检: {report['checks']}  淡入: {report['fade']}  高亮: {report['highlight']}")
        if any(report["checks"].values()):
            print("  [!] 存在违规帧，详见报告")
            exit_code = 1
    return exit_code


def main() -> int:
    """CLI。退出码：0 成功；1 自检有违规；2 输入/媒体/渲染错误；64 参数用法错误。"""
    parser = argparse.ArgumentParser(description="D 模块 · 基础动效（见 PRD.md）")
    parser.add_argument("--demo", action="store_true", help="用内置样例独立跑通全部功能")
    parser.add_argument("--video", help="输入视频路径")
    parser.add_argument("--srt", help="字幕 SRT 路径（与 --segments 二选一）")
    parser.add_argument("--segments", help="字幕片段 JSON 路径")
    parser.add_argument("--template", help="模板配置 JSON 路径（缺省用内置默认）")
    parser.add_argument("--orientation", choices=("auto", "portrait", "landscape"),
                        default="auto", help="按视频实际宽高自动判定方向（默认）")
    parser.add_argument("--chapters", help="章节切换点 JSON 路径（缺省自动生成）")
    parser.add_argument("--out", default="effects_output", help="输出目录")
    args = parser.parse_args()

    if args.demo:
        return run_demo(args.out)

    if not args.video or not (args.srt or args.segments):
        parser.error("非 demo 模式需要 --video 与 --srt/--segments")
    try:
        rc = _run_cli(args, parser)
    except EffectsError as e:
        print(f"[effects] {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return rc


def _run_cli(args, parser) -> int:
    if args.srt:
        segments = segments_from_srt(args.srt)
    else:
        try:
            segments = json.loads(Path(args.segments).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise InputError(f"segments JSON 读取失败: {args.segments}: {e}") from e
    segments = validate_segments(segments)
    tpl = load_template(args.template)
    if args.orientation == "auto":
        tpl["orientation"] = detect_orientation(args.video)
        print(f"[effects] 方向自动判定: {tpl['orientation']} "
              f"({'x'.join(map(str, ffprobe_size(args.video)))})")
    else:
        tpl["orientation"] = args.orientation
    if args.chapters:
        try:
            chapters = json.loads(Path(args.chapters).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise InputError(f"chapters JSON 读取失败: {args.chapters}: {e}") from e
        chapters = validate_chapters(chapters)
    else:
        chapters = auto_chapters(segments)
        print(f"[effects] 自动生成章节 {len(chapters)} 节: "
              + " / ".join(c["label"] for c in chapters))
    paths = render_pair(args.video, segments, tpl, chapters, args.out)
    report = check_frames(paths["light"]["mp4"], paths["light"]["ass"], tpl,
                          str(Path(args.out) / "check_report.json"))
    print(json.dumps({"outputs": paths, "checks": report["checks"]}, ensure_ascii=False, indent=2))
    return 0 if not any(report["checks"].values()) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())