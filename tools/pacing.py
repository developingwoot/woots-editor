"""Find stretches of a rendered cut that go too long without a visual change.

Usage:
    python pacing.py <preview.mp4> <edit.json> <transcript.json> [--max 30] [--target 15]

Detects every visual change in the render (camera-angle switches, hard cuts, graphics
appearing/leaving) with FFmpeg scene detection, then lists gaps longer than --max seconds
along with what is being said there, so the editor can look for a natural visual
(B-roll, a graphic, an angle change, a punch-in). Guideline, not a rule: don't force a change.
Writes <preview>.pacing.json.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def scene_changes(video: Path, threshold: float) -> list[float]:
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "scenes.txt"
        # metadata filter writes to a file; escape the Windows drive colon for the filter parser
        log_arg = str(log).replace("\\", "/").replace(":", "\\:")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-an",
             "-vf", f"select='gt(scene,{threshold})',metadata=print:file='{log_arg}'",
             "-f", "null", "-"],
            check=True,
        )
        text = log.read_text(encoding="utf-8") if log.exists() else ""
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", text)]


def duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(video)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def to_source(t: float, keeps) -> float:
    """Map a time in the cut back to the source footage (keeps are in OUTPUT order)."""
    elapsed = 0.0
    for s, e in keeps:
        if t <= elapsed + (e - s):
            return s + (t - elapsed)
        elapsed += e - s
    return keeps[-1][1]


def said_between(a: float, b: float, keeps, words) -> str:
    """Words spoken between output times a and b, walking the (possibly re-ordered) pieces."""
    out, elapsed = [], 0.0
    for s, e in keeps:
        lo, hi = max(a, elapsed), min(b, elapsed + e - s)
        if lo < hi:
            sa, sb = s + lo - elapsed, s + hi - elapsed
            out += [w["word"] for w in words if sa <= w["start"] < sb]
        elapsed += e - s
    return " ".join(out)


def mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--max", type=float, default=30.0, help="flag gaps longer than this (s)")
    ap.add_argument("--target", type=float, default=15.0, help="ideal spacing (s), for the summary")
    ap.add_argument("--threshold", type=float, default=0.3, help="scene-change sensitivity (0-1)")
    args = ap.parse_args()

    keeps = json.loads(args.plan.read_text(encoding="utf-8"))["keeps"]
    words = json.loads(args.transcript.read_text(encoding="utf-8"))["words"]
    total = duration(args.video)
    changes = scene_changes(args.video, args.threshold)

    marks = [0.0] + changes + [total]
    gaps = [(a, b) for a, b in zip(marks, marks[1:]) if b - a > 0.5]
    long_gaps = []
    for a, b in gaps:
        if b - a <= args.max:
            continue
        sa, sb = to_source(a, keeps), to_source(b, keeps)
        said = said_between(a, b, keeps, words)
        long_gaps.append({"out_start": round(a, 1), "out_end": round(b, 1), "length": round(b - a, 1),
                          "src_start": round(sa, 1), "src_end": round(sb, 1), "said": said})

    in_target = sum(1 for a, b in gaps if b - a <= args.target)
    report = {"duration": round(total, 1), "changes": len(changes),
              "avg_gap": round(total / (len(changes) + 1), 1),
              "gaps_within_target": in_target, "gaps_total": len(gaps),
              "long_gaps": long_gaps}
    out = args.video.with_suffix(".pacing.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{mmss(total)} long, {len(changes)} visual changes, average every {report['avg_gap']}s; "
          f"{len(long_gaps)} stretch(es) over {args.max:.0f}s:")
    for g in long_gaps:
        print(f"  {mmss(g['out_start'])}-{mmss(g['out_end'])} ({g['length']}s, source "
              f"{mmss(g['src_start'])}-{mmss(g['src_end'])}): {g['said'][:160]}...")
    print(f"-> {out}")


if __name__ == "__main__":
    sys.exit(main())
