"""Silences in the recordings, read from the sound itself (the word times of the transcript run on through a pause, so they cannot say how long it is).

`<name>.silence.json` caches them per recording: {rel: {"size", "mtime", "silences": [[start, end]]}}. The rough cut cuts out every silence longer than
max_pause_s (youtube-edit rough-cut.json), leaving a short breath each side.
"""
import os
import re
import subprocess
from pathlib import Path

import clipmap
import config
from sectionrender import FFMPEG

WORK = config.WORK
MIN_S = 0.3                         # a stretch this long that is quieter than the floor counts as a silence
VERSION = 3


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.silence.json"


def floor_db(file: str) -> float:
    """The level below which a recording counts as silent: 14 dB under its average level. Relative to the average, so the same material gives the same answer before and after
    its volume is normalized (a peak-relative floor did not: the room tone of the finished cut read as speech). Never above -30 or below -60."""
    r = subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-i", str(file), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return max(-60.0, min(-30.0, float(m.group(1)) - 14.0)) if m else -38.0


def detect(file: str) -> list:
    r = subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-i", str(file), "-vn", "-af", f"silencedetect=noise={floor_db(file):.1f}dB:d={MIN_S}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    out = [[max(0.0, a), b] for a, b in zip(starts, ends)]
    if len(starts) > len(ends):                                  # a recording that ends in silence
        out.append([max(0.0, starts[-1]), float("inf")])
    return out


def of_recording(work: str, name: str, folder: str, rel: str, cache: dict) -> list:
    f = os.path.join(folder, rel)
    try:
        st = os.stat(f)
    except OSError:
        return []
    e = cache.get(rel)
    if e and e.get("v") == VERSION and e.get("size") == st.st_size and e.get("mtime") == int(st.st_mtime):
        return e["silences"]
    sil = [[a, b if b != float("inf") else 1e9] for a, b in detect(f)]
    cache[rel] = {"v": VERSION, "size": st.st_size, "mtime": int(st.st_mtime), "silences": sil}
    return sil


def cut_silences(keep: list, silences: list, max_pause: float, pad: float, before_word: float | None = None, words: list | None = None) -> list:
    """The source-second ranges `keep` without the middle of every silence longer than max_pause: `pad` seconds of each silence stay after the speech
    and `before_word` (default `pad`) before the next word. The quiet end of a word ('enemy') is not loud enough to count as sound, so the speech side gets more."""
    before_word = pad if before_word is None else before_word
    out = []
    for a, z in keep:
        cur = [a]
        pieces = []
        for s, e in silences:
            if e - s <= max_pause or e <= a or s >= z:
                continue
            c0, c1 = max(a, s + pad), min(z, e - before_word)
            for w in words or ():                                   # never inside a word: the one before keeps its likely length (0.12 s + 0.05 s a letter, at most 0.6 s; the transcript's end of a word runs on into the pause), the next one its start
                if w[1] < c0 <= w[2] and w[1] >= s - 1.0:
                    c0 = max(c0, min(w[2], w[1] + min(0.6, 0.12 + 0.05 * len(re.sub("[^a-z]", "", str(w[0]).lower())))))      # a word needs about 0.12 s and 0.05 s a letter; the transcript's word end runs on into the pause
                if c0 < w[1] < c1 < w[2]:
                    c1 = w[1] - 0.05
            if c1 - c0 > 0.05:
                pieces.append((cur[0], c0))
                cur = [c1]
        pieces.append((cur[0], z))
        out += [[round(x, 3), round(y, 3)] for x, y in pieces if y - x > 0.3]
    return out
