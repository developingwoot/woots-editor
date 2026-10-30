"""Find "double cuts": two visible cuts within a moment of each other (reads as a glitch).

Usage:
    python doublecuts.py <work_dir> <name> [--gap 1.0]

Collects every visible cut in OUTPUT time from the plan files: edit joins (source jumps),
punch-in starts/ends, and full-frame overlay windows (B-roll, full-frame graphics) starting/ending.
Cuts that happen underneath a full-frame overlay are invisible and ignored. Any two visible cuts
closer than --gap seconds are reported with what caused them.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("name")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--video", type=Path, help="also scan this rendered preview (30 fps) for double cuts")
    args = ap.parse_args()
    load = lambda ext: json.loads((args.work / f"{args.name}.{ext}.json").read_text(encoding="utf-8")) \
        if (args.work / f"{args.name}.{ext}.json").exists() else None
    plan = load("edit")
    keeps = plan["keeps"]
    starts, el = [], 0.0
    for s, e in keeps:
        starts.append(el)
        el += e - s

    def out(t):
        for (s, e), st in zip(keeps, starts):          # half-open: a boundary belongs to the next piece
            if s - 1e-3 <= t < e - 1e-3:
                return st + max(t - s, 0)
        for (s, e), st in zip(keeps, starts):
            if abs(t - e) <= 1e-3:
                return st + e - s
        return None

    events = []                                     # (output time, description)
    for i in range(1, len(keeps)):
        if abs(keeps[i][0] - keeps[i - 1][1]) > 0.04:
            events.append((starts[i], f"edit cut (source {keeps[i-1][1]:.1f} -> {keeps[i][0]:.1f})"))
    for sh in (load("shots") or {}).get("shots", [])[1:]:
        t = out(sh["start"])
        if t is not None:
            events.append((t, f"camera angle change (source {sh['start']:.2f})"))
    for z in (load("zooms") or {}).get("zooms", []):
        a, b = out(z["src_start"]), out(z["src_end"])
        if a is not None:
            events.append((a, f"punch-in on {z['who']} starts"))
        if b is not None:
            events.append((b, f"punch-in on {z['who']} ends"))

    windows = []                                    # full-frame overlays hide what's underneath
    for b in load("broll") or []:
        a = out(b["src_start"])
        if a is not None:
            windows.append((a, a + b["dur"], f"B-roll {Path(b['file']).stem}"))
    for g in load("graphics") or []:
        if g.get("overlay"):
            continue                                # transparent overlays don't hide the picture
        a = out(g["src_start"])
        if a is None:
            continue
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", g["file"]], capture_output=True, text=True).stdout)
        for x, y in g.get("show") or [[0, dur]]:
            windows.append((a + x, a + y, f"graphic {Path(g['file']).stem}"))
    for a, b, lab in windows:
        events += [(a, f"{lab} in"), (b, f"{lab} out")]

    def hidden(t):
        return any(a + 0.02 < t < b - 0.02 for a, b, _ in windows)

    vis = sorted((t, d) for t, d in events if not hidden(t))
    merged = []                                     # same-instant events are one cut
    for t, d in vis:
        if merged and t - merged[-1][0] < 0.14:   # render.py snaps edges within 4 frames onto one frame
            merged[-1][1].append(d)
        else:
            merged.append((t, [d]))
    found = 0
    for (t0, d0), (t1, d1) in zip(merged, merged[1:]):
        if t1 - t0 < args.gap:
            found += 1
            print(f"{int(t0//60)}:{t0%60:05.2f} -> {int(t1//60)}:{t1%60:05.2f} ({t1-t0:.2f}s): "
                  f"{' + '.join(d0)}  |  {' + '.join(d1)}")
    print(f"{found} double cut(s) under {args.gap}s among {len(merged)} visible cuts (plan)")
    if args.video:
        # Safety net: scan the RENDER for hard picture changes closer than 0.7 s, outside overlays
        # (B-roll can have fast motion of its own).
        import numpy as np
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(args.video), "-vf",
                              "scale=96:54,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.float32)
        d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
        # A cut is an isolated spike: big change against calm neighbours. Runs of large changes
        # are motion (a hand near the lens), not cuts.
        calm = lambda k: 0 <= k < len(d) and d[k] < 12
        hard = [(i + 1) / 30 for i, v in enumerate(d)
                if v > 25 and calm(i - 2) and calm(i + 2)
                and not any(a + 0.1 < (i + 1) / 30 < b - 0.1 for a, b, _ in windows)]
        bad = [(a, b) for a, b in zip(hard, hard[1:]) if b - a < 0.7]  # cuts measure 55-86, motion 9-20
        for a, b in bad:
            print(f"  render: picture changes at {int(a//60)}:{a%60:05.2f} and {int(b//60)}:{b%60:05.2f}")
        print(f"{len(bad)} double cut(s) found in the render")


if __name__ == "__main__":
    sys.exit(main())
