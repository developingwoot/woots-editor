"""Track an object through a clip so a callout graphic can follow it.

Usage:
    python track.py <video> --at X,Y [--box 0.12] [--step 0.1] [--out track.json]

X,Y: the object's centre in the FIRST frame, as frame fractions (0-1). Each frame is
template-matched within a search window around the last position, and the template is
refreshed gradually so slow perspective/scale changes from a moving camera don't lose the lock.
Writes [[t, x, y], ...] (seconds, frame fractions) every --step seconds, plus a check image
(<out>.jpg) with the tracked point drawn on frames across the clip.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--at", required=True, help="object centre in the first frame, frame fractions X,Y")
    ap.add_argument("--box", type=float, default=0.12, help="template size as a fraction of frame width")
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ok, frame = cap.read()
    h, w = frame.shape[:2]
    scale = 960 / w                                   # track at 960 px wide for speed
    small = lambda f: cv2.cvtColor(cv2.resize(f, (960, int(h * scale))), cv2.COLOR_BGR2GRAY)
    g = small(frame)
    cx, cy = [float(v) for v in args.at.split(",")]
    px, py = cx * g.shape[1], cy * g.shape[0]
    half = int(args.box * 960 / 2)
    tmpl = g[int(py) - half:int(py) + half, int(px) - half:int(px) + half].astype(np.float32)
    search = half * 2

    pts, frames_for_check, i = [(0.0, cx, cy)], [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
        g = small(frame)
        x0, y0 = max(0, int(px) - half - search), max(0, int(py) - half - search)
        x1, y1 = min(g.shape[1], int(px) + half + search), min(g.shape[0], int(py) + half + search)
        win = g[y0:y1, x0:x1].astype(np.float32)
        res = cv2.matchTemplate(win, tmpl, cv2.TM_CCOEFF_NORMED)
        _, conf, _, loc = cv2.minMaxLoc(res)
        px, py = x0 + loc[0] + half, y0 + loc[1] + half
        patch = g[int(py) - half:int(py) + half, int(px) - half:int(px) + half].astype(np.float32)
        if patch.shape == tmpl.shape and conf > 0.5:
            tmpl = 0.85 * tmpl + 0.15 * patch        # slowly adapt to perspective change
        t = i / fps
        if t + 1e-6 >= pts[-1][0] + args.step:
            pts.append((round(t, 3), round(px / g.shape[1], 4), round(py / g.shape[0], 4)))
        if i % int(fps) == 0:
            f = frame.copy()
            cv2.circle(f, (int(px / scale), int(py / scale)), int(half / scale), (0, 140, 255), 6)
            cv2.putText(f, f"{t:.1f}s conf {conf:.2f}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 255, 255), 3)
            frames_for_check.append(cv2.resize(f, (480, int(480 * h / w))))
    out = args.out or args.video.with_suffix(".track.json")
    out.write_text(json.dumps(pts), encoding="utf-8")
    if frames_for_check:
        cv2.imwrite(str(out.with_suffix(".jpg")), np.hstack(frames_for_check[:6]))
    print(f"{len(pts)} keyframes over {i / fps:.1f}s -> {out}")


if __name__ == "__main__":
    sys.exit(main())
