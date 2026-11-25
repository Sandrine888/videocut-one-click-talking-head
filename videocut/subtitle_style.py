"""Static styling and layout contract shared by render, effects, and verification."""

from dataclasses import dataclass
from importlib.resources import files
import json
import math
import os
import re
import unicodedata


@dataclass(frozen=True)
class SubtitleStyle:
    width: int
    height: int
    orientation: str
    font: str
    font_px: int
    margin_x: int
    margin_y: int
    padding_px: int
    outline_px: float
    target_min_chars: int
    max_chars: int
    max_lines: int
    text_color: str
    outline_color: str
    shadow_color: str
    shadow_opacity: float
    accent_color: str
    fade_in_ms: int
    chapter_badge_ms: int

    @property
    def text_width_px(self) -> int:
        return self.width - 2 * (self.margin_x + self.padding_px + math.ceil(self.outline_px))


@dataclass(frozen=True)
class SubtitleCue:
    cue_id: str
    start_ms: int
    end_ms: int
    text: str


def load_style(width: int, height: int, *, font: str | None = None) -> SubtitleStyle:
    """Resolve the shared template in square-pixel output-frame units."""
    if min(width, height) < 1:
        raise ValueError("Video dimensions must be positive")
    template = json.loads(files("videocut").joinpath("template_defaults.json").read_text(encoding="utf-8"))
    orientation = "portrait" if height > width else "landscape"
    preset = template[orientation]
    font_px = max(1, round(min(width, height) * preset["font_short_edge_ratio"]))
    font_name = font or template["font_windows" if os.name == "nt" else "font_other"]
    if any(c in font_name for c in ",\r\n"):
        raise ValueError("The font family name cannot contain a comma or newline")
    return SubtitleStyle(
        width=width,
        height=height,
        orientation=orientation,
        font=font_name,
        font_px=font_px,
        margin_x=math.ceil(width * template["side_margin_ratio"]),
        margin_y=math.ceil(height * template["bottom_margin_ratio"]),
        padding_px=max(1, math.ceil(font_px * 0.20)),
        outline_px=round(font_px * 0.052, 2),
        target_min_chars=preset["target_min_chars"],
        max_chars=preset["max_chars"],
        max_lines=template["max_lines"],
        text_color=template["text_color"],
        outline_color=template["outline_color"],
        shadow_color=template["shadow_color"],
        shadow_opacity=template["shadow_opacity"],
        accent_color=template["accent_color"],
        fade_in_ms=template["fade_in_ms"],
        chapter_badge_ms=template["chapter_badge_ms"],
    )


def _is_visible(character: str) -> bool:
    return not character.isspace() and unicodedata.category(character)[0] not in {"C", "M"}


def visible_count(text: str) -> int:
    """Count visible base code points, including punctuation, excluding spaces and marks."""
    return sum(map(_is_visible, text))


def estimated_width(text: str, style: SubtitleStyle) -> int:
    """Approximate libass glyph advance. Visual QA still uses rendered frames."""
    widths = []
    for character in text:
        if character.isspace():
            widths.append(0.43)
        elif _is_visible(character):
            if unicodedata.east_asian_width(character) in {"F", "W", "A"}:
                widths.append(0.90)
            elif character in "MWmw@%":
                widths.append(1.02)
            elif character.isascii():
                widths.append(0.74)
            else:
                widths.append(1.1)
    return math.ceil(sum(widths) * style.font_px)


def check_layout(cue: SubtitleCue, lines: tuple[str, ...], style: SubtitleStyle) -> dict:
    """Structured, JSON-compatible diagnostics for E. Rows are indexed from 1."""
    issues = []
    if len(lines) > style.max_lines:
        issues.append({"code": "too_many_lines", "actual": len(lines), "limit": style.max_lines})
    for number, line in enumerate(lines, 1):
        count = visible_count(line)
        width = estimated_width(line, style)
        if count > style.max_chars:
            issues.append({"code": "too_many_characters", "line": number, "actual": count, "limit": style.max_chars})
        if width > style.text_width_px:
            issues.append({"code": "estimated_width_overflow", "line": number, "actual": width, "limit": style.text_width_px})
    return {
        "cue_id": cue.cue_id,
        "start_ms": cue.start_ms,
        "end_ms": cue.end_ms,
        "lines": list(lines),
        "ok": not issues,
        "issues": issues,
    }


_CLOSING = "，。！？：；、）》】」』〉〕］｝,.!?;:%)]}”’…"
_OPENING = "（《【「『〈〔［｛([{“‘"
_NUMBER = r"[+\-−]?[¥￥$€£]?\d+(?:[.,:/\-]\d+)*(?:\s*(?:万亿|万元|亿美元|亿元|公里|毫秒|个月|kg|ms|km|cm|GB|MB|[%％年月日元亿万秒岁米]))*"
_WORD = r"[A-Za-z]+[A-Za-z0-9]*(?:(?:[._+\-/'’][A-Za-z0-9]+)|[+#])*"


def _fits(line: str, style: SubtitleStyle) -> bool:
    return 0 < visible_count(line) <= style.max_chars and estimated_width(line, style) <= style.text_width_px


def layout_cue(cue: SubtitleCue, style: SubtitleStyle, *, protected_terms=()) -> tuple[str, ...]:
    """Preserve valid upstream lines. Otherwise choose a display break at a token boundary."""
    original = tuple(line.strip() for line in cue.text.splitlines() if line.strip())
    if len(original) != 1 or not original or _fits(original[0], style):
        return original

    text = original[0]
    terms = sorted({term for term in protected_terms if term}, key=lambda term: (-len(term), term))
    prefixes = [re.escape(term) for term in terms]
    tokens = re.finditer("|".join([*prefixes, _WORD, _NUMBER, r"\s+", r"."]), text)
    candidates = []
    for token in tokens:
        left, right = text[:token.end()].rstrip(), text[token.end():].lstrip()
        if not left or not right or left[-1] in _OPENING or right[0] in _CLOSING:
            continue
        if unicodedata.category(right[0])[0] in {"C", "M"}:
            continue
        if not (_fits(left, style) and _fits(right, style)):
            continue
        boundary_bonus = style.font_px * (3 if left[-1] in _CLOSING else int(token.group().isspace()))
        balance = abs(estimated_width(left, style) - estimated_width(right, style))
        candidates.append((balance - boundary_bonus, left, right))
    if not candidates:
        return original
    _, left, right = min(candidates)
    return left, right


def _ass_color(color: str, opacity: float = 1.0) -> str:
    red, green, blue = (color[index:index + 2] for index in (1, 3, 5))
    alpha = round(255 * (1 - opacity))
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def _ass_time(milliseconds: int) -> str:
    centiseconds = (milliseconds + 5) // 10
    seconds, fraction = divmod(centiseconds, 100)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour}:{minute:02d}:{second:02d}.{fraction:02d}"


def _ass_text(line: str) -> str:
    # Guard literal backslashes and escape override delimiters before joining explicit lines.
    return line.replace("\\", "\\\u200b").replace("{", r"\{").replace("}", r"\}")


def _accent_span(lines: tuple[str, ...], terms: tuple[str, ...]) -> tuple[int, int, int] | None:
    for term in terms:
        if not term.strip():
            continue
        pattern = re.escape(term)
        if term[0].isascii() and term[0].isalnum():
            pattern = r"(?<![A-Za-z0-9])" + pattern
        if term[-1].isascii() and term[-1].isalnum():
            pattern += r"(?![A-Za-z0-9])"
        for row, line in enumerate(lines):
            match = re.search(pattern, line)
            if match:
                return row, match.start(), match.end()
    return None


def _colored_text(lines: tuple[str, ...], span: tuple[int, int, int] | None, style: SubtitleStyle) -> str:
    rows = list(map(_ass_text, lines))
    if span is not None:
        row, start, end = span
        line = lines[row]
        accent = _ass_color(style.accent_color)[4:]
        base = _ass_color(style.text_color)[4:]
        rows[row] = (
            _ass_text(line[:start]) + rf"{{\1c&H{accent}&}}"
            + _ass_text(line[start:end]) + rf"{{\1c&H{base}&}}" + _ass_text(line[end:])
        )
    return r"\N".join(rows)


def build_ass(cues: list[SubtitleCue], style: SubtitleStyle, *, protected_terms=(), accent_terms=()) -> tuple[str, list[dict]]:
    """Return styled libass events and the exact display rows checked by E."""
    accent_terms = tuple(accent_terms)
    protected_terms = (*protected_terms, *accent_terms)
    shadow = _ass_color(style.shadow_color, style.shadow_opacity)
    shadow_blur = round(style.font_px * 0.10, 2)
    side = style.margin_x + style.padding_px
    bottom = style.margin_y + style.padding_px + math.ceil(style.outline_px + shadow_blur)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.width}
PlayResY: {style.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: RoleA,{style.font},{style.font_px},{_ass_color(style.text_color)},{_ass_color(style.accent_color)},{_ass_color(style.outline_color, 0.79)},{shadow},-1,0,0,0,100,100,0,0,1,{style.outline_px},0,2,{side},{side},{bottom},1
Style: RoleAShadow,{style.font},{style.font_px},{shadow},{shadow},{shadow},{shadow},-1,0,0,0,100,100,0,0,1,{style.outline_px * 1.6:.2f},0,2,{side},{side},{bottom - max(1, round(style.font_px * 0.05))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    checks = []
    for cue in cues:
        lines = layout_cue(cue, style, protected_terms=protected_terms)
        check = check_layout(cue, lines, style)
        checks.append(check)
        start, end = _ass_time(cue.start_ms), _ass_time(cue.end_ms)
        if start == end:
            check["issues"].append({"code": "below_render_time_resolution", "actual": cue.end_ms - cue.start_ms, "limit": 10})
            check["ok"] = False
        if check["ok"]:
            span = _accent_span(lines, accent_terms)
            check["accent"] = lines[span[0]][span[1]:span[2]] if span is not None else None
            plain = r"\N".join(map(_ass_text, lines))
            shadow_text = rf"{{\blur{shadow_blur}}}" + plain
            events.append(f"Dialogue: 0,{start},{end},RoleAShadow,,0,0,0,,{shadow_text}\n")
            events.append(f"Dialogue: 1,{start},{end},RoleA,,0,0,0,,{_colored_text(lines, span, style)}\n")
    return header + "".join(events), checks
