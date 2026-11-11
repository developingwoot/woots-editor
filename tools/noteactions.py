"""Small edits Claude can ask for when it applies the host's notes, done by the app instead of by rewriting the whole beat map:

  {"note": id, "do": "web",   "time": "0:31", "url": "https://...", "find": "words on the page to highlight", "seconds": 5}
        capture the public page (webcapture.py) and put it over the clip playing at that time
  {"note": id, "do": "sfx",   "time": "0:31", "sound": "<a file name from sounds.txt>"}
        a sound effect from the host's SFX folder at that time
  {"note": id, "do": "angle", "file": "<the other recording named in the note>"}
        the other camera's picture over the host's take, the take's sound kept: the recording is found in the takes near the note by its sound
        (anglesync.py) and its picture goes over every kept stretch of the cut it covers

`time` is minutes:seconds into the video as the host saw it (like the notes); the clip playing then is found from the beat map's times.
run() does them and writes the beat map once, through projectstore; an action that cannot be done is reported, never half done.
"""
import os
import re
import time
from pathlib import Path

import config
import projectstore

KINDS = ("web", "sfx", "angle")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mts", ".webm"}
NEAR_S = 60.0                  # an angle is looked for in the takes of the beats this close to the note


def seconds_of(t) -> float | None:
    """'3:22' / '1:02:03' / 31 -> seconds; None when it cannot be read."""
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return float(t) if t >= 0 else None
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d+):(\d{1,2}(?:\.\d+)?)\s*", str(t or ""))
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def parse(ans: dict, open_ids: set) -> list:
    """The well-formed actions of Claude's answer for notes that are open."""
    out = []
    for a in ans.get("edits") or []:
        if not isinstance(a, dict) or a.get("note") not in open_ids or a.get("do") not in KINDS:
            continue
        if a["do"] in ("web", "sfx") and seconds_of(a.get("time")) is None:
            continue
        if a["do"] == "web" and not str(a.get("url") or "").strip():
            continue
        if a["do"] == "sfx" and not str(a.get("sound") or "").strip():
            continue
        if a["do"] == "angle" and not str(a.get("file") or "").strip():
            continue
        out.append(a)
    return out


def beat_at(beats: list, t: float):
    """(beat, seconds into it) of the clip playing at t, from the plan's times; the last clip when t is past the end. Skipped beats are not in the video."""
    live = [b for b in beats if not b.get("skip") and (b.get("aroll") or b.get("vo"))]
    for b in live:
        s = float(b.get("start") or 0)
        if s <= t < s + float(b.get("dur") or 0):
            return b, round(t - s, 2)
    if not live:
        raise ValueError("there are no clips in the plan")
    b = min(live, key=lambda x: abs(float(x.get("start") or 0) - t))
    return b, 0.0


def add_sfx(beats: list, t: float, sound: str) -> str:
    import finalrender
    f, why = finalrender.resolve_sfx(sound)
    if not f:
        raise ValueError(f"the sound '{sound}' was not found ({why})")
    b, at = beat_at(beats, t)
    au = b.setdefault("audio", {})
    au["sfx"] = list(au.get("sfx") or []) + [f"{Path(f).stem} @ {at}"]
    return f"Added the sound {Path(f).stem} at {_clock(t)} (heard from the preview on: the rough cut has no sound effects)"


def add_web(work: str, beats: list, a: dict, env=None) -> str:
    import cutview
    import webcapture
    url = webcapture.check_url(a["url"])
    b, at = beat_at(beats, seconds_of(a["time"]))
    find = " ".join(str(a.get("find") or "").split())[:300]
    got = webcapture.capture_apart(url, config.WORK / work / "web-broll", "scroll" if find else "still", find, webcapture.seconds_of(a.get("seconds", 5)), env=env)
    if not got.get("ok"):
        raise ValueError(got.get("error") or "the page could not be captured")
    from urllib.parse import urlsplit
    cutview.put_web(b, {"file": got["file"], "dur": got.get("seconds", 5.0), "at": at, "url": got.get("url", url), "title": got.get("title", ""),
                        "captured": time.strftime("%Y-%m-%d")})
    host = urlsplit(url).hostname or url
    return f"Put the web page {host} over the clip at {_clock(seconds_of(a['time']))}" + ("" if not find or got.get("found") else " (the words to highlight were not on the page)")


def _kept(b: dict) -> list:
    a = b.get("aroll") or {}
    return a.get("keep") or ([[a["in"], a["out"]]] if "in" in a and "out" in a else [])


def angle_inserts(b: dict, file: str, start: float, length: float) -> list:
    """B-roll inserts that show recording `file` (which starts at `start` seconds of the beat's take and runs `length`) over every kept stretch it covers."""
    out, t = [], 0.0
    for k_in, k_out in _kept(b):
        s0, s1 = max(k_in, start), min(k_out, start + length)
        if s1 - s0 > 0.3:
            out.append({"file": file, "in": round(s0 - start, 3), "dur": round(s1 - s0, 3), "at": round(t + s0 - k_in, 3), "why": "The other angle, the take's sound kept",
                        "transition": "cut", "angle": True})
        t += k_out - k_in
    return out


def add_angle(work: str, name: str, beats: list, file: str, t: float, find=None, length_of=None) -> str:
    """The other angle over the clips it covers. `find` and `length_of` (tests) stand in for anglesync.locate and anglesync.duration."""
    import anglesync
    import shootplan
    folder, _ = shootplan.footage_folder(work, name)
    p = Path(str(file).strip().strip('"'))
    p = p if p.is_absolute() else Path(folder or ".") / p
    p = Path(os.path.abspath(str(p)))
    if p.suffix.lower() not in VIDEO_EXT or not p.is_file() or not folder or not config.inside(folder, p):
        raise ValueError("the other recording must be a video in this video's footage folder")
    find = find or anglesync.locate
    near = [b for b in beats if not b.get("skip") and b.get("aroll") and abs(float(b.get("start") or 0) - t) <= NEAR_S]
    best = None
    for rel in dict.fromkeys(b["aroll"]["rel"] for b in near):
        spans = [k for b in near if b["aroll"]["rel"] == rel for k in _kept(b)]
        lo, hi = min(k[0] for k in spans) - NEAR_S, max(k[1] for k in spans) + NEAR_S
        start, score = find(str(p), str(Path(folder) / rel), lo, hi)
        if score >= anglesync.MIN_SCORE and (not best or score > best[2]):
            best = (rel, start, score)
    if not best:
        raise ValueError(f"{p.name} could not be lined up by its sound with the clips near {_clock(t)}")
    rel, start, _ = best
    length = (length_of or anglesync.duration)(p)
    covered = []
    for b in beats:
        if b.get("skip") or (b.get("aroll") or {}).get("rel") != rel:
            continue
        ins = angle_inserts(b, str(p), start, length)
        if ins:
            on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
            on["broll"] = ins + [x for x in on.get("broll", []) if x.get("file") != str(p)]        # under any other cutaway
            covered.append(b)
    if not covered:
        raise ValueError(f"{p.name} was found in the recording, but at a moment the cut does not use")
    first = min(float(b.get("start") or 0) + x["at"] for b in covered for x in b["on_screen"]["broll"] if x.get("angle"))
    return f"Used the other angle ({p.name}) from {_clock(first)}, with the sound of your take"


def _clock(t: float) -> str:
    t = int(round(t or 0))
    return f"{t // 60}:{t % 60:02d}"


def run(work: str, name: str, actions: list, note_times: dict, env=None, log=print, find=None, length_of=None) -> dict:
    """Do the actions on the beat map; write it once. {"changes": [...], "failed": {note id: why}}."""
    import beatmap
    p = config.WORK / work / f"{name}.beatmap.json"
    bm = beatmap.read_json(p)
    if not bm:
        return {"changes": [], "failed": {a["note"]: "there is no plan" for a in actions}}
    changes, failed, by_note = [], {}, {}
    for a in actions:
        try:
            log(f"{a['do']} for note {a['note']}")
            if a["do"] == "sfx":
                text = add_sfx(bm["beats"], seconds_of(a["time"]), str(a["sound"]))
            elif a["do"] == "web":
                text = add_web(work, bm["beats"], a, env)
            else:
                text = add_angle(work, name, bm["beats"], str(a["file"]), float(note_times.get(a["note"]) or 0), find, length_of)
            changes.append(text)
            by_note.setdefault(a["note"], []).append(text)
        except Exception as e:                                          # noqa: BLE001  (one action that cannot be done is reported, the rest go on)
            failed[a["note"]] = str(e)
    if changes:
        projectstore.write_json(p, bm, why="notes applied")
    return {"changes": changes, "failed": failed, "by_note": by_note}


def sounds_list() -> str:
    """The SFX files Claude can choose from (sounds.txt), one name a line."""
    import sfxkit
    return "\n".join(sfxkit.rel(f) for f in sfxkit.files())
