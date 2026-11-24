"""真片实测：用社团项目原片 + 既有剪辑后 SRT 跑 D 模块（一次性脚本）。"""
import json
import sys
from pathlib import Path

import pysubs2

sys.path.insert(0, str(Path(__file__).parent))
from videocut.render import effects as fx

SRC = Path(r"C:\Users\gjx81\Desktop\qoder cn工作区\一键剪口播项目d\社团项目\微信视频2026-11-21_213120_116_cut.mp4")
SRT = Path(r"C:\Users\gjx81\Desktop\deepseek工作区\剪辑工作\videocut_口播成片\videocut\微信视频2026-11-21_213120_116_cut.srt")
OUT = SRC.parent / "d_output"

subs = pysubs2.load(str(SRT), encoding="utf-8")
segments = [
    {"index": i + 1, "start": e.start / 1000.0, "end": e.end / 1000.0, "text": e.text}
    for i, e in enumerate(subs)
]
chapters = [
    {"start": 0.0, "label": "开场"},
    {"start": 13.44, "label": "第2节 · ASR 与 LLM"},
    {"start": 25.86, "label": "第3节 · 时间戳对齐"},
    {"start": 37.48, "label": "第4节 · 术语与收尾"},
]
(OUT / "input").mkdir(parents=True, exist_ok=True)
(OUT / "input" / "segments.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "input" / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")

tpl = fx.load_template()
tpl["orientation"] = "portrait"
paths = fx.render_pair(str(SRC), segments, tpl, chapters, str(OUT))
report = fx.check_frames(paths["light"]["mp4"], paths["light"]["ass"], tpl, str(OUT / "check_report.json"))
print(json.dumps({"outputs": paths, "checks": report["checks"],
                  "fade": report["fade"], "highlight": report["highlight"],
                  "frames": report["frames_extracted"]}, ensure_ascii=False, indent=2))