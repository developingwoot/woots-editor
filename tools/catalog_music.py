"""Catalog a music folder: tempo, loudness, energy, brightness and how much the energy swings.

Usage:
    python catalog_music.py <music_dir> [--out catalog.json]

The numbers help pick beds: a good under-dialogue bed has steady energy (low "swing"),
moderate tempo and no huge drops/builds. Mood tags come from the title plus these numbers
and should be checked by ear; the user knows their library.
"""
import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln


def analyze(path: Path) -> dict:
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    rms = librosa.feature.rms(y=y, frame_length=4096, hop_length=2048)[0]
    db = 20 * np.log10(rms + 1e-9)
    # Energy per 5 s window; "swing" = spread between quiet and loud passages.
    win = int(5 * sr / 2048)
    blocks = np.array([db[i:i + win].mean() for i in range(0, len(db) - win, win)]) if len(db) > win else db
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
    loud = pyln.Meter(sr).integrated_loudness(y)
    return {"file": path.name, "duration": round(len(y) / sr, 1), "bpm": round(tempo),
            "lufs": round(loud, 1), "swing_db": round(float(np.percentile(blocks, 90) - np.percentile(blocks, 10)), 1),
            "brightness_hz": round(centroid)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_dir", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows = []
    for f in sorted(args.music_dir.iterdir()):
        if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
            r = analyze(f)
            rows.append(r)
            print(f"{r['duration']:6.0f}s {r['bpm']:4d} bpm {r['lufs']:6.1f} LUFS swing {r['swing_db']:5.1f} dB "
                  f"bright {r['brightness_hz']:5d}  {r['file']}", flush=True)
    out = args.out or args.music_dir / "_catalog.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    sys.exit(main())
