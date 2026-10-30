"""Make a timestamped contact sheet (8x6 grid) for each video, for picking B-roll moments.

Usage:
    python contact.py <out_dir> <video> [<video> ...]

Samples 48 frames evenly across each clip by seeking straight to each point (fast even
for hour-long files on the NAS, unlike decoding the whole clip), labels each frame with its
timestamp, and writes <out_dir>/<video name>.jpg.
"""
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

N = 48


def duration(v: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(v)], capture_output=True, text=True).stdout
    return float(out.split()[0])


def grab(v: Path, t: float, dst: Path):
    h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
    label = f"drawtext=text='{h}\\:{m:02}\\:{s:02}':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "quiet", "-y", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1",
                    "-vf", f"scale=240:135:force_original_aspect_ratio=decrease,pad=240:135:-1:-1,{label}",
                    str(dst)])


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for v in map(Path, sys.argv[2:]):
        dur = duration(v)
        step = dur / N
        with tempfile.TemporaryDirectory() as tmp:
            frames = [Path(tmp) / f"f{i:02}.png" for i in range(N)]
            with ThreadPoolExecutor(8) as pool:
                for i, f in enumerate(frames):
                    pool.submit(grab, v, step * (i + 0.5), f)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "quiet", "-y", "-i", str(Path(tmp) / "f%02d.png"),
                            "-vf", "tile=8x6", "-frames:v", "1", str(out_dir / f"{v.stem}.jpg")])
        print(f"{v.stem}.jpg: every {step:.0f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())

