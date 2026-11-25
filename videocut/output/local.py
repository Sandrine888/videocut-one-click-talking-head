"""Local static subtitle burn-in. This entry point accepts SRT from any producer."""

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import tempfile

from ..subtitle_style import SubtitleCue, build_ass, load_style


_CLOCK = r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})"
_TIMING = re.compile(rf"^{_CLOCK}\s*-->\s*{_CLOCK}(?:[ \t].*)?$")


def _milliseconds(parts: tuple[str, ...]) -> int:
    hours, minutes, seconds, fraction = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + fraction


def read_srt(path: str | Path) -> list[SubtitleCue]:
    """Read plain-text UTF-8 SRT without changing cue text or timing."""
    content = Path(path).read_text(encoding="utf-8-sig").strip()
    if not content:
        raise ValueError("SRT contains no cues")
    cues = []
    for position, block in enumerate(re.split(r"\n[ \t]*\n", content), 1):
        identifier, separator, body = block.partition("\n")
        timing, _, text = body.partition("\n")
        match = _TIMING.fullmatch(timing.strip())
        if not separator or not identifier.strip() or not match or not text.strip():
            raise ValueError(f"Invalid SRT cue at position {position}")
        start = _milliseconds(match.groups()[:4])
        end = _milliseconds(match.groups()[4:])
        if end <= start:
            raise ValueError(f"Cue {identifier} ends before or at its start")
        if cues and start < cues[-1].end_ms:
            raise ValueError(f"Cue {identifier} overlaps the previous cue or is out of order")
        cues.append(SubtitleCue(identifier.strip(), start, end, text))
    return cues


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    stream_index: int
    audio_codec: str | None


def _probe_video(path: Path) -> VideoInfo:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])
    video = next((
        item for item in streams
        if item["codec_type"] == "video" and not item.get("disposition", {}).get("attached_pic")
    ), None)
    if video is None:
        raise ValueError("Input has no playable video stream")
    if video.get("sample_aspect_ratio") not in {None, "N/A", "0:1", "1:1"}:
        raise ValueError("Static subtitle burn-in needs a square-pixel input")
    width, height = video["width"], video["height"]
    rotation = next((
        data["rotation"] for data in video.get("side_data_list", []) if "rotation" in data
    ), 0)
    if rotation % 180:
        width, height = height, width
    audio = next((item for item in streams if item["codec_type"] == "audio"), None)
    return VideoInfo(width, height, video["index"], audio["codec_name"] if audio else None)


def burn_subtitles(
    video_path: str | Path,
    srt_path: str | Path,
    output_path: str | Path,
    *,
    report_path: str | Path | None = None,
    protected_terms: tuple[str, ...] = (),
    accent_terms: tuple[str, ...] = (),
    font: str | None = None,
) -> dict:
    """Burn static captions and return the structured report shared with verification."""
    source, srt, target = (Path(path).resolve() for path in (video_path, srt_path, output_path))
    report_target = Path(report_path).resolve() if report_path is not None else None
    if len({source, srt, target, report_target}) != 4:
        raise ValueError("Input, SRT, output, and report must be distinct files")
    if target.suffix.lower() != ".mp4":
        raise ValueError("Output path must end in .mp4")
    cues = read_srt(srt)
    video = _probe_video(source)
    style = load_style(video.width, video.height, font=font)
    ass, checks = build_ass(cues, style, protected_terms=protected_terms, accent_terms=accent_terms)
    failed = sum(not item["ok"] for item in checks)
    report = {
        "schema_version": 1,
        "ok": failed == 0,
        "rendered": False,
        "cue_count": len(checks),
        "failed_cues": failed,
        "style": asdict(style),
        "cues": checks,
    }
    def write_report() -> None:
        if report_target is not None:
            report_target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_report()
    if failed:
        first = next(item for item in checks if not item["ok"])
        raise ValueError(f"{failed} cue(s) failed layout. First: {first['cue_id']} {first['issues']}")

    # A fixed filter-local filename avoids Windows drive and quote escaping in the filter graph.
    with tempfile.TemporaryDirectory(prefix="videocut-subtitles-") as temp:
        (Path(temp) / "captions.ass").write_text(ass, encoding="utf-8")
        with tempfile.NamedTemporaryFile(prefix=".videocut-", suffix=".mp4", dir=target.parent, delete=False) as stage:
            pending = Path(stage.name)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(source), "-map", f"0:{video.stream_index}", "-map", "0:a:0?",
                    "-vf", "ass=captions.ass", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                    "-c:a", "copy" if video.audio_codec == "aac" else "aac",
                    "-movflags", "+faststart", str(pending),
                ],
                check=True, cwd=temp, capture_output=True, text=True, encoding="utf-8",
            )
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    report["rendered"] = True
    write_report()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Burn VideoCut static subtitles from UTF-8 SRT.")
    parser.add_argument("video", type=Path)
    parser.add_argument("srt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, help="Write per-cue layout results as JSON.")
    parser.add_argument("--font", help="Override the default installed CJK font family.")
    parser.add_argument("--protect-term", action="append", default=[], help="Keep a term together at line breaks.")
    parser.add_argument("--accent-term", action="append", default=[], help="Highlight the first matching term per cue.")
    args = parser.parse_args()
    try:
        result = burn_subtitles(
            args.video, args.srt, args.output, report_path=args.report,
            protected_terms=tuple(args.protect_term), accent_terms=tuple(args.accent_term), font=args.font,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Subtitle burn-in failed: {getattr(exc, 'stderr', None) or exc}\n")
    print(f"{result['cue_count']} cues passed ({result['style']['orientation']})")


if __name__ == "__main__":
    main()
