"""Explain what is on screen at given times of a rendered edit (for acting on review notes).

Usage:
    python whatsat.py <work_dir> <name> <mm:ss> [<mm:ss> ...]

For each output time: the source time, what is said, whether a B-roll insert, graphic or
punch-in is on screen, and any cut (editorial or pause) within 1.5 s.
"""
import json
import sys
from pathlib import Path


def main():
    work, name = Path(sys.argv[1]), sys.argv[2]
    load = lambda ext: json.loads((work / f"{name}.{ext}.json").read_text(encoding="utf-8")) \
        if (work / f"{name}.{ext}.json").exists() else None
    keeps = load("edit")["keeps"]
    words = load("transcript")["words"]
    speakers = load("speakers") or []
    broll = load("broll") or []
    gfx = load("graphics") or []
    zooms = (load("zooms") or {}).get("zooms", [])

    starts, el = [], 0.0
    for s, e in keeps:
        starts.append(el)
        el += e - s

    def to_src(o):
        for (s, e), st in zip(keeps, starts):
            if o <= st + (e - s):
                return s + (o - st)
        return keeps[-1][1]

    for arg in sys.argv[3:]:
        m, s = arg.split(":")
        o = int(m) * 60 + float(s)
        t = to_src(o)
        said = " ".join(w["word"] for w in words if t - 1.5 <= w["start"] <= t + 3)
        who = next((x["speaker"] for x in speakers if x["start"] - 0.3 <= t <= x["end"] + 0.3), "-")
        print(f"\n{arg}  (source {t:.1f}s, {who}): \"{said}\"")
        for i, b in enumerate(broll):
            if b["src_start"] - 1 <= t <= b["src_start"] + b["dur"] + 1:
                print(f"  B-roll #{i} {b['file']} in={b['in']} dur={b['dur']} at src {b['src_start']} ({b.get('why','')})")
        for g in gfx:
            if g["src_start"] <= t <= g["src_start"] + 60:
                print(f"  graphic {Path(g['file']).name} anchored {g['src_start']} (local {t - g['src_start']:.1f}s)")
        for z in zooms:
            if z["src_start"] - 1 <= t <= z["src_end"] + 1:
                print(f"  punch-in on {z['who']} {z['src_start']:.1f}-{z['src_end']:.1f} ({z['reason']})")
        for (s, e), st in zip(keeps, starts):
            if abs(st - o) < 1.5 and st > 0:
                print(f"  cut at output {st:.1f}s (jumps source {prev_end:.1f} -> {s:.1f})")
            prev_end = e


if __name__ == "__main__":
    sys.exit(main())
