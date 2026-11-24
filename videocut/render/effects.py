"""D 模块 · 基础动效（PRD.md v1.0）

功能：字幕淡入（80–150ms）、每条最多 1 个重点词高亮、章节角标、
「无动效/轻动效」对照样片、逐帧几何自检。

技术路线（已定死，见 PRD 2.2）：
    pysubs2 生成 ASS 特效标签 -> ffmpeg 内置 libass 单次烧录（-c:a copy，不改时长）。

边界：只读 A 的模板配置；不改 C 的断句文本；不碰 B/E 的文件。
独立运行：python -m videocut.render.effects --demo
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pysubs2

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


def load_template(path: Optional[str] = None) -> Dict:
    """读配置、校验区间、缺字段用默认值补齐。fade_in_ms 越界钳制到 80–150。"""
    user = {}
    if path:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    tpl = _deep_merge(DEFAULT_TEMPLATE, user)

    fade = tpl["effects"]["fade_in_ms"]
    if not (FADE_MIN_MS <= fade <= FADE_MAX_MS):
        clamped = max(FADE_MIN_MS, min(FADE_MAX_MS, fade))
        print(f"[effects] 警告: fade_in_ms={fade} 越界，钳制为 {clamped}")
        tpl["effects"]["fade_in_ms"] = clamped

    if tpl["orientation"] not in PLAY_RES:
        raise ValueError(f"orientation 必须是 portrait/landscape，收到 {tpl['orientation']}")
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
    chapters = chapters or []
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
        alignment=2,  # 底部居中
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
            alignment=9,  # 右上锚点
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
        print("[effects] FFmpeg 错误:\n" + result.stderr[-800:])
        return False
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
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(video).stem
    paths = {}
    for key, effects_on in (("noeffects", False), ("light", True)):
        ass_path = out / f"{stem}_{key}.ass"
        mp4_path = out / f"{stem}_{key}.mp4"
        subs = build_ass(segments, template, chapters, effects_on=effects_on)
        subs.save(str(ass_path), encoding="utf-8")
        ok = burn(video, str(ass_path), str(mp4_path))
        if not ok:
            raise RuntimeError(f"烧录失败: {mp4_path}")
        paths[key] = {"ass": str(ass_path), "mp4": str(mp4_path)}
    return paths


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
    report = {
        "video": str(video),
        "ass": str(ass_path),
        "orientation": orient,
        "play_res": [w, h],
        "duration_s": round(duration, 3),
        "frames_extracted": extracted,
        "frame_dir": str(frame_dir),
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
    parser = argparse.ArgumentParser(description="D 模块 · 基础动效（见 PRD.md）")
    parser.add_argument("--demo", action="store_true", help="用内置样例独立跑通全部功能")
    parser.add_argument("--video", help="输入视频路径")
    parser.add_argument("--segments", help="字幕片段 JSON 路径")
    parser.add_argument("--template", help="模板配置 JSON 路径（缺省用内置默认）")
    parser.add_argument("--chapters", help="章节切换点 JSON 路径（可选）")
    parser.add_argument("--out", default="effects_output", help="输出目录")
    args = parser.parse_args()

    if args.demo:
        return run_demo(args.out)

    if not args.video or not args.segments:
        parser.error("非 demo 模式需要 --video 与 --segments")
    with open(args.segments, "r", encoding="utf-8") as f:
        segments = json.load(f)
    chapters = None
    if args.chapters:
        with open(args.chapters, "r", encoding="utf-8") as f:
            chapters = json.load(f)
    tpl = load_template(args.template)
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