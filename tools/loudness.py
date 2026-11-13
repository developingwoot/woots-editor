"""One volume for the whole cut (the host, 2026-10-29: the volume was not normalized).

The renderer used to measure each piece by itself and bring it to the target; a piece of a few seconds measures differently from the next one of the same
recording (a pause, a loud word), so the level jumped at every jump cut. Now each RECORDING is measured once, whole, and every piece of it gets the same gain.
`<name>.loudness.json` caches the measure: {rel: {"size", "mtime", "lufs"}}.
"""
import os
from pathlib import Path

import clipmap
import config
import sectionrender

WORK = config.WORK
TARGET = sectionrender.LEVEL_TARGET
MAX_GAIN = 15.0


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.loudness.json"


HOP = 0.5            # seconds between the points of the slow level curve
SMOOTH_S = 8.0     # how slowly it moves: the voice is followed over about this long, never word by word
MAX_DEV_DB = 8.0     # the most it ever turns a stretch up or down


def deviation(x, sr: int, smooth_s: float = SMOOTH_S, max_db: float = MAX_DEV_DB) -> list:
    """The slow level curve of a voice: dB to add, every HOP seconds, so the speech comes to its own average (the host moves, leans in, speaks softer or louder
    over tens of seconds). Only the speech counts (pauses and room noise do not pull it), the curve is smooth, and it is 0 where there is no speech.
    `x` is mono float samples. Not a compressor: nothing happens inside a word or a sentence."""
    import numpy as np
    n = int(sr * HOP)
    blocks = len(x) // n
    if blocks < 4:
        return [0.0] * max(blocks, 1)
    p = np.asarray(x[:blocks * n], dtype=np.float64).reshape(blocks, n)
    db = 10 * np.log10(np.mean(p * p, axis=1) + 1e-10)
    speech = db > max(-60.0, np.percentile(db, 95) - 18.0)
    if speech.sum() < 4:
        return [0.0] * blocks
    mean = float(db[speech].mean())
    k = int(smooth_s / HOP) * 2 + 1
    w = np.exp(-0.5 * ((np.arange(k) - k // 2) / (smooth_s / HOP / 2)) ** 2)
    num = np.convolve(np.where(speech, db, 0.0), w, mode="same")
    den = np.convolve(speech.astype(float), w, mode="same")
    local = np.where(den > 0.5, num / np.maximum(den, 1e-9), mean)
    weight = np.clip(den / 2.0, 0.0, 1.0)                                      # little speech nearby: leave it alone
    dev = np.clip((mean - local) * weight, -max_db, max_db)
    return [round(float(v), 2) for v in dev]


def dev_at(dev: list, t: float) -> float:
    """The curve's dB at second `t`."""
    if not dev:
        return 0.0
    import numpy as np
    return float(np.interp(t, (np.arange(len(dev)) + 0.5) * HOP, dev))


def apply_curve(audio, sr: int, dev: list, t0: float = 0.0):
    """`audio` (samples x channels, starting at second `t0` of the recording) with the curve laid over it."""
    import numpy as np
    t = t0 + np.arange(len(audio)) / sr
    g = np.interp(t, (np.arange(len(dev)) + 0.5) * HOP, dev) if dev else np.zeros(len(audio))
    return (audio * (10 ** (g / 20))[:, None]).astype(np.float32)


def recording_curve(folder: str, rel: str, cache: dict) -> list:
    """The slow level curve of a whole recording (cached beside the loudness measure); [] when its sound cannot be read."""
    f = os.path.join(folder, rel)
    try:
        st = os.stat(f)
    except OSError:
        return []
    key = "dev:" + rel
    e = cache.get(key)
    if e and e.get("size") == st.st_size and e.get("mtime") == int(st.st_mtime) and e.get("v") == 1:
        return e["db"]
    import subprocess
    import numpy as np
    r = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-v", "error", "-i", f, "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    db = deviation(np.frombuffer(r.stdout, np.float32), 16000) if r.returncode == 0 and r.stdout else []
    cache[key] = {"size": st.st_size, "mtime": int(st.st_mtime), "v": 1, "db": db}
    return db


def gain_for(lufs: float | None) -> float | None:
    """dB that brings a recording measured at `lufs` to the target (None when it could not be measured)."""
    if lufs is None or lufs <= -60:
        return None
    return round(max(-MAX_GAIN, min(MAX_GAIN, TARGET - lufs)), 2)


def of_recording(folder: str, rel: str, cache: dict) -> float | None:
    f = os.path.join(folder, rel)
    try:
        st = os.stat(f)
    except OSError:
        return None
    e = cache.get(rel)
    if e and e.get("size") == st.st_size and e.get("mtime") == int(st.st_mtime) and e.get("lufs") is not None:
        return e["lufs"]
    lufs = sectionrender.measure_lufs(f, 0.0, 36000.0)
    cache[rel] = {"size": st.st_size, "mtime": int(st.st_mtime), "lufs": lufs}
    return lufs


def set_gains(work: str, name: str, edit: dict, folder: str) -> int:
    """Put `gain_db` on every segment of the edit from its whole recording. Returns how many recordings were measured or read."""
    cache = clipmap.read_json(path(work, name), None) or {}
    seen, curves = {}, {}
    for seg in edit["segments"]:
        if seg.get("audio_src") or seg.get("mute"):
            continue
        src = seg["src"]
        if src not in seen:
            try:
                rel = os.path.relpath(src, folder)
            except ValueError:
                rel = src
            seen[src] = gain_for(of_recording(folder, rel, cache))
            curves[src] = recording_curve(folder, rel, cache) if seen[src] is not None else []
        if seen[src] is not None:
            seg["gain_db"] = seen[src]
            curve = curves[src]
            if curve:                                                         # the voice's slow ups and downs: the piece starts and ends at the gain the curve asks
                seg["gain_db"] = round(seen[src] + dev_at(curve, float(seg["in"])), 2)
                seg["gain_to_db"] = round(seen[src] + dev_at(curve, float(seg["out"])), 2)
    clipmap.write_json(path(work, name), cache)
    return len(seen)
