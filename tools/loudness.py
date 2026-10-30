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
    seen = {}
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
        if seen[src] is not None:
            seg["gain_db"] = seen[src]
    clipmap.write_json(path(work, name), cache)
    return len(seen)
