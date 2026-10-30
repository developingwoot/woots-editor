"""Build review clips for the host's intro decisions (music candidates, audio/video sync).

Usage:
    python intro_previews.py music <splice.json> <out_dir> <candidates.json>
    python intro_previews.py sync  <video> <start_s> <out.mp4> [--offsets 0 50 100 150 200] [--dur 8]

music: renders the intro + title card (540p) once per candidate bed, each with the same picture and voice,
       using splice.add_intro_music (candidates.json = [{"name", "file", "from", "length", "peak_at", ...}]).
sync:  the same dialogue repeated with the AUDIO delayed by each offset (ms) relative to the picture,
       labelled A, B, C... (A = offset 0 = as recorded). Delaying audio fixes a recording where the sound
       arrives before the picture (camera/capture latency), which is common with OBS.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

import assemble
import render
import splice

SR = render.SR


def music(cfg_path, out_dir, cands_path):
    c = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    cands = json.loads(Path(cands_path).read_text(encoding="utf-8"))
    br = {"fade": 0.3, "whoosh_db": -2, **c["bridge"]}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = Fraction(30)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        v, a, n = splice.take_piece("intro", c["intro"], c["folder"], fps, (1920, 1080), br, tmp, False, True, ["end"])
        nc = assemble.packets(Path(c["title_card"]["file"]))
        card = np.zeros((round(nc * SR / 30), 2), np.float32)
        for s in c["title_card"].get("sfx", []):
            x = render.decode(Path(s["file"]), tmp)
            x = x * (0.25 / (np.abs(x).max() or 1)) * 10 ** (s.get("gain_db", 0) / 20)
            p0 = int(s["at"] * SR)
            card[p0:p0 + len(x)] += x[: len(card) - p0]
        # picture: intro + title card, 540p, built once
        pic = tmp / "pic.mp4"
        assemble.ff("-i", v, "-i", c["title_card"]["file"], "-filter_complex",
                    f"[0:v]fps=30,scale=960:540,format=yuv420p[a];[1:v]fps=30,scale=960:540,format=yuv420p[b];[a][b]concat=n=2:v=1:a=0[v]",
                    "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", pic)
        for cand in cands:
            pieces = [("intro", [], "", a.copy(), n, {}), ("title_card", [], "", card.copy(), nc, {})]
            spec = {**c.get("intro_music", {}), **{k: v for k, v in cand.items() if k != "name"}}
            splice.add_intro_music(spec, pieces, tmp, fps)
            mix = np.vstack([pieces[0][3], pieces[1][3]])
            wav = tmp / "mix.wav"
            sf.write(str(wav), mix, SR, subtype="FLOAT")
            out = out_dir / f"intro-music-{cand['name']}.mp4"
            assemble.ff("-i", pic, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", out)
            print(f"  {out.name}: {out.stat().st_size / 2**20:.1f} MB")


def sync(video, start, out, offsets, dur):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        segs = []
        for i, off in enumerate(offsets):
            label = chr(ord("A") + i)
            seg = tmp / f"s{i}.mp4"
            # picture at [start, start+dur); sound taken from `off` ms EARLIER = the sound is delayed by `off`
            assemble.ff("-ss", f"{start:.3f}", "-t", f"{dur}", "-i", video,
                        "-ss", f"{start - off / 1000:.3f}", "-t", f"{dur}", "-i", video,
                        "-map", "0:v:0", "-map", "1:a:0", "-vf",
                        f"scale=960:540,drawbox=x=0:y=0:w=150:h=110:color=black@0.7:t=fill,"
                        f"drawtext=text='{label}':x=40:y=10:fontsize=90:fontcolor=white,format=yuv420p",
                        "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "160k",
                        "-ar", "48000", "-ac", "2", seg)
            segs.append(seg)
            if i < len(offsets) - 1:                                     # a short black beat between takes
                gap = tmp / f"g{i}.mp4"
                assemble.ff("-f", "lavfi", "-i", "color=c=black:s=960x540:r=30:d=0.8", "-f", "lavfi",
                            "-i", "anullsrc=r=48000:cl=stereo", "-t", "0.8", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", gap)
                segs.append(gap)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
        assemble.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", out)
    print(f"  {Path(out).name}: {Path(out).stat().st_size / 2**20:.1f} MB; " +
          ", ".join(f"{chr(65 + i)} = audio {o} ms later" for i, o in enumerate(offsets)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("music"); m.add_argument("cfg"); m.add_argument("out_dir"); m.add_argument("cands")
    s = sub.add_parser("sync"); s.add_argument("video"); s.add_argument("start", type=float); s.add_argument("out")
    s.add_argument("--offsets", type=int, nargs="+", default=[0, 50, 100, 150, 200]); s.add_argument("--dur", type=float, default=8)
    a = ap.parse_args()
    if a.cmd == "music":
        music(a.cfg, a.out_dir, a.cands)
    else:
        sync(a.video, a.start, a.out, a.offsets, a.dur)


if __name__ == "__main__":
    sys.exit(main())
