"""Rebuild only the audio of a render and mux it into an existing video (picture copied, not re-encoded).

Usage:
    python remix_audio.py <edit.json> <source video> <video in> <video out> --audio <audio.json>

For changes that touch only the sound (music beds, SFX, levels, voice chain): about 2 minutes instead
of a 15-minute full render. <source video> is what the video was rendered from (the original for a
final, the proxy for a preview); <video in> must have been rendered from the SAME edit.json keeps.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import render


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path)
    ap.add_argument("source", type=Path)
    ap.add_argument("video_in", type=Path)
    ap.add_argument("video_out", type=Path)
    ap.add_argument("--audio", type=Path, required=True, help="music + SFX plan")
    ap.add_argument("--bitrate", default="320k")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    fps = render.probe_fps(args.source)
    frames = [(a, b) for a, b in ((round(s * fps), round(e * fps)) for s, e in plan["keeps"]) if b > a]
    want = float(sum(b - a for a, b in frames) / fps)
    have = render.probe_duration(args.video_in)
    if abs(have - want) > 0.1:
        sys.exit(f"{args.video_in.name} is {have:.2f}s but edit.json gives {want:.2f}s: it was rendered from "
                 f"another plan, so the new audio would not line up. Do a full render instead.")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        chain = json.loads(args.audio.read_text(encoding="utf-8")).get("voice_chain")
        render.build_audio(args.source, frames, fps, wav, chain)
        mixed = Path(tmp) / "mixed.wav"
        render.mix_audio(wav, args.audio, frames, fps, mixed, Path(tmp), blocks=plan.get("sections"))
        args.video_out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(args.video_in), "-i", str(mixed),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", args.bitrate,
                        "-shortest", "-movflags", "+faststart", str(args.video_out)], check=True)
    print(f"remixed audio -> {args.video_out}")


if __name__ == "__main__":
    sys.exit(main())
