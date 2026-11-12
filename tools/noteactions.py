"""Small edits Claude can ask for when it applies the host's notes, done by the app instead of by rewriting the whole beat map:

  {"note": id, "do": "web",   "time": "0:31", "url": "https://...", "find": "words on the page to highlight", "seconds": 5}
        capture the public page (webcapture.py) and put it over the clip playing at that time
  {"note": id, "do": "sfx",   "time": "0:31", "sound": "<a file name from sounds.txt>"}
        a sound effect from the host's SFX folder at that time
  {"note": id, "do": "text",  "time": "0:31", "text": "*0.4 mm nozzle, not 0.6", "kind": "correction|detail"}
        a short line of on-screen text (textcards.py) on the clip playing at that time
  {"note": id, "do": "angle", "file": "<the other recording named in the note>"}
        the other camera's picture over the host's take, the take's sound kept: the recording is found in the takes near the note by its sound
        (anglesync.py) and its picture goes over every kept stretch of the cut it covers
  {"note": id, "do": "music", "from": "0:00", "until": "1:30" or "", "track": "<a name from music.txt>"}
        background music: audio.music on every clip in that stretch (to the end when `until` is empty)
  {"note": id, "do": "blur", "time": "0:31", "what": "the username on the printer screen"}
        a blur (blur.py) on the clip at that time with no box yet: the host draws it on the frame and it is followed through the clip
  {"note": id, "do": "cut", "time": "2:05", "words": "or at least not right now"}
        those words taken out of the clip at that time (or the one before or after), the rest of the take kept: also on a clip marked good
  {"note": id, "do": "broll", "time": "10:41", "file": "<a recording from recordings.txt>", "from": 0, "seconds": 5, "speed": 1}
        a recording laid over the picture of the clip at that time, its own sound not used (a timelapse, a shot from another day)

`time` is minutes:seconds into the video as the host saw it (like the notes); the clip playing then is found from the beat map's times.
run() does them and writes the beat map once, through projectstore; an action that cannot be done is reported, never half done.
"""
import os
import re
import time
from pathlib import Path

import config
import projectstore

KINDS = ("web", "sfx", "angle", "text", "music", "blur", "cut", "broll")
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
        if a["do"] in ("web", "sfx", "text", "blur", "cut", "broll") and seconds_of(a.get("time")) is None:
            continue
        if a["do"] == "cut" and not str(a.get("words") or "").strip():
            continue
        if a["do"] == "broll" and not str(a.get("file") or "").strip():
            continue
        if a["do"] == "text" and not str(a.get("text") or "").strip():
            continue
        if a["do"] == "web" and not str(a.get("url") or "").strip():
            continue
        if a["do"] == "sfx" and not str(a.get("sound") or "").strip():
            continue
        if a["do"] == "angle" and not str(a.get("file") or "").strip():
            continue
        if a["do"] == "music" and not str(a.get("track") or "").strip():
            continue
        out.append(a)
    return out


def _span(b: dict, times: dict | None) -> tuple:
    return times[b["id"]] if times and b["id"] in times else (float(b.get("start") or 0), float(b.get("dur") or 0))


def beat_at(beats: list, t: float, times: dict | None = None):
    """(beat, seconds into it) of the clip playing at t; the nearest clip when t falls in no clip. `times` = {beat id: (start, dur)} where each clip really
    plays (makeversion.clip_times): only those clips are in the video. Without it the plan's own times are used (skipped beats are not in the video)."""
    live = [b for b in beats if not b.get("skip") and (b.get("aroll") or b.get("vo")) and (not times or b["id"] in times)]
    for b in live:
        s, d = _span(b, times)
        if s <= t < s + d:
            return b, round(t - s, 2)
    if not live:
        raise ValueError("there are no clips in the plan")
    b = min(live, key=lambda x: abs(_span(x, times)[0] - t))
    return b, 0.0


def add_sfx(beats: list, t: float, sound: str, times: dict | None = None) -> str:
    import finalrender
    f, why = finalrender.resolve_sfx(sound)
    if not f:
        raise ValueError(f"the sound '{sound}' was not found ({why})")
    b, at = beat_at(beats, t, times)
    au = b.setdefault("audio", {})
    au["sfx"] = list(au.get("sfx") or []) + [f"{Path(f).stem} @ {at}"]
    return f"Added the sound {Path(f).stem} at {_clock(t)} (heard from the preview on: the rough cut has no sound effects)"


def add_text(beats: list, t: float, text: str, kind: str = "correction", times: dict | None = None) -> str:
    """On-screen text (textcards.py) on the clip playing at t: a correction of something misspoken, or a detail."""
    import skillrules
    import textcards
    b, at = beat_at(beats, t, times)
    e = textcards.entry({"text": text, "kind": kind, "at": at}, float(b.get("dur") or 0), skillrules.rules()["text_card_s"])
    if not e:
        raise ValueError("the text to show was empty")
    on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
    on["text"] = [x for x in on.get("text") or [] if x.get("text") != e["text"]] + [e]
    return f"Showed “{e['text']}” on screen at {_clock(t)}"


def add_web(work: str, beats: list, a: dict, env=None, times: dict | None = None) -> str:
    import cutview
    import webcapture
    url = webcapture.check_url(a["url"])
    b, at = beat_at(beats, seconds_of(a["time"]), times)
    find = " ".join(str(a.get("find") or "").split())[:300]
    got = webcapture.capture_apart(url, config.WORK / work / "web-broll", "scroll" if find else "still", find, webcapture.seconds_of(a.get("seconds", 5)), env=env)
    if not got.get("ok"):
        raise ValueError(got.get("error") or "the page could not be captured")
    from urllib.parse import urlsplit
    cutview.put_web(b, {"file": got["file"], "dur": got.get("seconds", 5.0), "at": at, "url": got.get("url", url), "title": got.get("title", ""),
                        "captured": time.strftime("%Y-%m-%d")})
    host = urlsplit(url).hostname or url
    return f"Put the web page {host} over the clip at {_clock(seconds_of(a['time']))}" + ("" if not find or got.get("found") else " (the words to highlight were not on the page)")


def add_music(beats: list, a: dict, times: dict | None = None) -> str:
    """A music bed (audio.music on each clip from `from` to `until`; builder.music_beds turns a run of them into one bed). `until` empty = to the end."""
    import finalrender
    f, why = finalrender.resolve_music(str(a.get("track") or ""))
    if not f:
        raise ValueError(f"the music '{a.get('track')}' could not be used ({why})")
    t0 = seconds_of(a.get("from")) or 0.0
    t1 = seconds_of(a.get("until"))
    t1 = float("inf") if t1 is None else t1
    live = [b for b in beats if not b.get("skip") and (b.get("aroll") or b.get("vo")) and (not times or b["id"] in times)]
    got = [b for b in live if _span(b, times)[0] < t1 and _span(b, times)[0] + _span(b, times)[1] > t0]
    if not got:
        raise ValueError("no clip plays in that stretch")
    for b in got:
        b.setdefault("audio", {})["music"] = f.stem
    end = max(_span(b, times)[0] + _span(b, times)[1] for b in got)
    return f"Put the music {f.stem} under {_clock(min(_span(b, times)[0] for b in got))} to {_clock(end)} (heard from the preview on: the rough cut has no music)"


def music_list() -> str:
    """The tracks Claude can choose from (music.txt): name | tempo | length, tracks with vocals left out."""
    import shortsaudio
    cat = shortsaudio.catalog()
    rows = []
    for t in shortsaudio.tracks():
        c = cat.get(Path(t["file"]).name.lower(), {})
        rows.append(" | ".join(x for x in (t["name"], f"{t['bpm']} bpm" if t.get("bpm") else "", f"{round(c['duration'])} s" if c.get("duration") else "", t["note"]) if x))
    return "\n".join(rows)


def _norm(w: str) -> str:
    return re.sub(r"[^\w']+", "", str(w).lower())


def cut_words(beats: list, t: float, words: str, times: dict | None = None) -> str:
    """Take the words out of the clip at t (or the clip before or after it): the take keeps playing around them, like a jump cut. A clip the host marked good
    can lose words this way: the host asked for it."""
    want = [x for x in (_norm(w) for w in str(words).split()) if x]
    if not want:
        raise ValueError("no words to take out were given")
    live = [b for b in beats if not b.get("skip") and b.get("aroll") and (not times or b["id"] in times)]
    if not live:
        raise ValueError("there are no clips in the plan")
    here, _ = beat_at(beats, t, times)
    k = next((i for i, b in enumerate(live) if b is here), 0)
    for b in [live[k]] + live[max(0, k - 1):k] + live[k + 1:k + 2]:
        a = b["aroll"]
        keep = _kept(b)
        ws = [w for w in a.get("words") or [] if any(k0 - 0.001 <= (w[1] + w[2]) / 2 <= k1 + 0.001 for k0, k1 in keep)]
        nw = [_norm(w[0]) for w in ws]
        hit = next((i for i in range(len(nw) - len(want) + 1) if nw[i:i + len(want)] == want), None)
        if hit is None:
            continue
        first, last = ws[hit], ws[hit + len(want) - 1]
        lo = (ws[hit - 1][2] + first[1]) / 2 if hit > 0 else min(k0 for k0, _ in keep)          # from the gap before the first word
        hi = (last[2] + ws[hit + len(want)][1]) / 2 if hit + len(want) < len(ws) else max(k1 for _, k1 in keep)
        new = []
        for k0, k1 in keep:
            for s0, s1 in ((k0, min(k1, lo)), (max(k0, hi), k1)):
                if s1 - s0 >= 0.3:
                    new.append([round(s0, 3), round(s1, 3)])
        if not new:
            raise ValueError("those words are the whole clip: take the clip out instead")
        a["keep"] = new if len(new) > 1 else None
        a["in"], a["out"] = new[0][0], new[-1][1]
        a["dur"] = b["dur"] = round(sum(s1 - s0 for s0, s1 in new), 2)
        return f"Took out “{' '.join(w[0] for w in ws[hit:hit + len(want)])}” at {_clock(_span(b, times)[0])}"
    raise ValueError(f"the words “{words}” were not found in the clip at {_clock(t)}")


def add_broll(work: str, name: str, beats: list, a: dict, times: dict | None = None) -> str:
    """A recording of the footage folder shown over the clip at `time` (its own sound is not used): a timelapse, a shot from another day."""
    import footageview
    import shootplan
    folder, _ = shootplan.footage_folder(work, name)
    if not folder:
        raise ValueError("the footage folder is not set")
    want = str(a.get("file") or "").strip().strip('"')
    p = Path(want) if Path(want).is_absolute() else Path(folder) / want
    p = Path(os.path.abspath(str(p)))
    if not p.is_file():                                     # only the file's name was given: look for it in the footage folder
        got = [f for f in Path(folder).rglob("*") if f.is_file() and f.name.lower() == Path(want).name.lower()]
        p = got[0] if len(got) == 1 else p
    if p.suffix.lower() not in VIDEO_EXT or not p.is_file() or not config.inside(folder, p):
        raise ValueError(f"the recording “{want}” was not found in this video's footage folder")
    rel = os.path.relpath(str(p), str(folder))
    length = footageview._durations(work, Path(folder), [rel]).get(rel)
    t = seconds_of(a["time"])
    b, at = beat_at(beats, t, times)
    speed = min(8.0, max(0.25, float(a.get("speed") or 1.0)))
    dur = max(1.0, min(float(a.get("seconds") or 4.0), 12.0))
    dur = min(dur, max(1.0, float(b.get("dur") or 0)))
    at = round(min(at, max(0.0, float(b.get("dur") or 0) - dur)), 2)
    src = max(0.0, float(a.get("from") or 0))
    if length:
        src = min(src, max(0.0, float(length) - dur * speed))
    on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
    on["broll"] = list(on.get("broll") or []) + [{"file": rel.replace("\\", "/"), "in": round(src, 2), "dur": round(dur, 2), "at": at,
                                                  "why": "A note asked for it", **({"speed": speed} if speed != 1.0 else {})}]
    return f"Showed {p.name} over the clip at {_clock(_span(b, times)[0] + at)} for {dur:g} seconds" + (f" at {speed:g}x speed" if speed != 1.0 else "")


def recordings_list(work: str, name: str) -> str:
    """The recordings of the footage folder Claude can lay over the picture (recordings.txt): path | seconds."""
    import footageview
    import shootplan
    folder, _ = shootplan.footage_folder(work, name)
    if not folder or not Path(folder).is_dir():
        return ""
    rels = sorted(os.path.relpath(str(f), str(folder)).replace("\\", "/") for f in Path(folder).rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXT)
    lens = footageview._durations(work, Path(folder), rels)
    return "\n".join(f"{r} | {round(lens[r])} s" if lens.get(r) else r for r in rels)


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


def add_angle(work: str, name: str, beats: list, file: str, t: float, find=None, length_of=None, times: dict | None = None) -> str:
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
    near = [b for b in beats if not b.get("skip") and b.get("aroll") and (not times or b["id"] in times) and abs(_span(b, times)[0] - t) <= NEAR_S]
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
    first = min(_span(b, times)[0] + x["at"] for b in covered for x in b["on_screen"]["broll"] if x.get("angle"))
    return f"Used the other angle ({p.name}) from {_clock(first)}, with the sound of your take"


def _clock(t: float) -> str:
    t = int(round(t or 0))
    return f"{t // 60}:{t % 60:02d}"


def run(work: str, name: str, actions: list, note_times: dict, env=None, log=print, find=None, length_of=None, times: dict | None = None) -> dict:
    """Do the actions on the beat map; write it once. {"changes": [...], "failed": {note id: why}}. `times`: where each clip really plays in the
    video the notes were made on (makeversion.clip_times); without it the plan's own times are used."""
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
                text = add_sfx(bm["beats"], seconds_of(a["time"]), str(a["sound"]), times)
            elif a["do"] == "web":
                text = add_web(work, bm["beats"], a, env, times)
            elif a["do"] == "text":
                text = add_text(bm["beats"], seconds_of(a["time"]), str(a["text"]), "detail" if a.get("kind") == "detail" else "correction", times)
            elif a["do"] == "music":
                text = add_music(bm["beats"], a, times)
            elif a["do"] == "cut":
                text = cut_words(bm["beats"], seconds_of(a["time"]), str(a["words"]), times)
            elif a["do"] == "broll":
                text = add_broll(work, name, bm["beats"], a, times)
            elif a["do"] == "blur":
                import blur
                e = blur.ask(bm["beats"], seconds_of(a["time"]), str(a.get("what") or ""), times)
                text = f"A blur box for {e['what'] or 'the part of the picture'} at {_clock(seconds_of(a['time']))}: place it over the frame (the Blur list under the player)"
            else:
                text = add_angle(work, name, bm["beats"], str(a["file"]), float(note_times.get(a["note"]) or 0), find, length_of, times)
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
