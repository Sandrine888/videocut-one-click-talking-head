"""PRD 第6节 AC3/AC4 可执行验收检查（一次性脚本，验收后可删）。"""
import json
import re
import subprocess
from pathlib import Path

import pysubs2

POS_RE = re.compile(r"\\pos\((\d+),(\d+)\)")


def dur(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


def streams(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height", "-of", "json", str(p)],
        capture_output=True, text=True)
    return json.loads(r.stdout)["streams"]


for orient in ("portrait", "landscape"):
    d = Path("demo_output") / orient
    src = Path("demo_output") / f"test_{orient}.mp4"
    on = pysubs2.load(str(d / f"test_{orient}_light.ass"))
    off = pysubs2.load(str(d / f"test_{orient}_noeffects.ass"))
    on_seg = [(e.start, e.end) for e in on if e.style == "Default"]
    off_seg = [(e.start, e.end) for e in off if e.style == "Default"]
    assert on_seg == off_seg, "AC4 时间轴不一致"

    badges = [e for e in on if e.style == "Badge"]
    assert len(badges) == 2, "AC3 角标数"
    W, H = (1080, 1920) if orient == "portrait" else (1920, 1080)
    for b in badges:
        m = POS_RE.search(b.text)
        assert m, "AC3 角标缺 pos"
        x, y = map(int, m.groups())
        assert x <= W * 0.92 + 1 and y >= 0, "AC3 角标越界"

    d0 = dur(src)
    for key in ("noeffects", "light"):
        out = d / f"test_{orient}_{key}.mp4"
        d1 = dur(out)
        assert abs(d1 - d0) < 0.05, f"AC4 时长变化 {d0}->{d1}"
        s_in, s_out = streams(src), streams(out)
        a_in = next(s for s in s_in if s["codec_type"] == "audio")
        a_out = next(s for s in s_out if s["codec_type"] == "audio")
        v_in = next(s for s in s_in if s["codec_type"] == "video")
        v_out = next(s for s in s_out if s["codec_type"] == "video")
        assert a_in["codec_name"] == a_out["codec_name"], "AC4 音频被重编码"
        assert (v_out["width"], v_out["height"]) == (v_in["width"], v_in["height"]), "AC4 画幅变化"
    print(f"{orient}: AC3/AC4 通过 (时长 {d0:.3f}s 不变, 音频 {a_out['codec_name']} copy, 画幅不变, 时间轴逐条一致)")

print("ALL PASS")