"""A short from a pile of raw footage: a folder of recordings and b-roll, no finished video.

  scan(folder)                         -> the video files directly in the folder
  tell_apart(files, wd)                -> {file: {"kind": "talk"|"broll", "words", "dur", "transcript"}} once transcribe.py has read the talking ones
  mistakes(words)                      -> [[a, b], ...] source seconds that are a restart, a repeat or a stammer (recut's rules): cut out of every short automatically
  new_project(work, name, folder, info) writes <name>.shorts.json with `sources` (talk first, then b-roll) and mode "raw"
  prompt(work, name, count)            -> what Claude is given: the talking recordings' transcripts with the mistakes marked, and the b-roll clips
  import_candidates(work, name, path)  -> Claude's answer, checked by code (every range inside its file, a complete thought, no abandoned take), added as shorts

A short is `ranges` ({"src", "a", "b"}: the best take of each line, from any talking recording) plus `overlays` (b-roll shown over the words, sound unchanged).
The numbers (how many words make a recording a talking one, how long a b-roll cut runs, how early the picture comes in) are in the youtube-shorts skill.
"""
import json
import re
import time
from pathlib import Path

import config
import footage_cfg
import recut
import shorts as sh
import shortsapp
import shortsplan
import skillrules

WORK = config.WORK


def scan(folder) -> list:
    """The video files directly in a folder, by name (sub-folders are not entered: two recordings with the same name would collide)."""
    p = Path(folder)
    if not p.is_dir():
        raise ValueError("that is not a folder")
    return sorted((f for f in p.iterdir() if f.is_file() and f.suffix.lower() in footage_cfg.VIDEO_EXT and not f.name.startswith(".")), key=lambda f: f.name.lower())


def transcript_of(wd: Path, f: Path) -> Path:
    return Path(wd) / f"{f.stem}.transcript.json"


def is_talking(words: int, dur: float) -> bool:
    r = skillrules.shorts()
    return words >= r["raw_min_words"] and dur > 0 and words / dur >= r["raw_min_words_per_s"]


def load_words(path) -> list:
    """[[word, start, end], ...]: the shape recut's mistake finders read."""
    tr = json.loads(Path(path).read_text(encoding="utf-8"))
    return [[w["word"], w["start"], w["end"]] for w in tr.get("words", [])]


def tell_apart(files: list, wd) -> dict:
    """Which recordings are the host talking and which are b-roll, from what was read out of them. A file with no sound, or too few words said too slowly, is b-roll."""
    out = {}
    for f in files:
        tf = transcript_of(wd, f)
        words, dur = 0, 0.0
        if tf.is_file():
            tr = json.loads(tf.read_text(encoding="utf-8"))
            words, dur = len(tr.get("words", [])), float(tr.get("duration") or 0)
        out[f] = {"kind": "talk" if is_talking(words, dur) else "broll", "words": words, "dur": dur, "transcript": str(tf) if tf.is_file() else ""}
    return out


def mistakes(words: list) -> list:
    """Source-second spans to cut from a talking recording: a take abandoned before a restart, a phrase or sentence said again (the later one stays), a stammer."""
    if not words:
        return []
    drop = recut.repeated_phrase_drops(words)
    drop |= recut.repeated_sentence_drops(words, drop)
    drop |= recut.stammer_drops(words, drop)
    spans, cur = [], []
    for i in sorted(drop):
        if cur and i != cur[-1] + 1:
            spans.append(cur)
            cur = []
        cur.append(i)
    if cur:
        spans.append(cur)
    out = [[round(words[c[0]][1], 2), round(words[c[-1]][2], 2)] for c in spans]
    return [s for s in out if s[1] - s[0] >= 0.05]


def duration(path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(path))
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return round(n / fps, 2) if n and fps else 0.0


def contact_sheet(path, dest: Path, frames: int = 4, width: int = 360):
    """A strip of frames across a clip, so Claude can look at the b-roll."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(path))
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    tiles = []
    for k in range(frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / frames))
        ok, fr = cap.read()
        if ok:
            tiles.append(cv2.resize(fr, (width, int(fr.shape[0] * width / fr.shape[1]))))
    cap.release()
    if not tiles:
        return False
    h = min(t.shape[0] for t in tiles)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), np.hstack([t[:h] for t in tiles]), [cv2.IMWRITE_JPEG_QUALITY, 78])
    return True


def new_project(work: str, name: str, folder, info: dict):
    """Write the shorts project. Talking recordings are sources t1, t2 ..., b-roll b1, b2 ... (talk first: the first source is where crops and speakers come from)."""
    talk = [f for f, i in info.items() if i["kind"] == "talk"]
    broll = [f for f, i in info.items() if i["kind"] == "broll"]
    if not talk:
        raise ValueError("no talking recording in that folder: the shorts are built on someone talking")
    sources = []
    for n, f in enumerate(talk, 1):
        sources.append({"id": f"t{n}", "path": str(f).replace("\\", "/"), "transcript": info[f]["transcript"].replace("\\", "/"), "kind": "talk",
                        "mistakes": mistakes(load_words(info[f]["transcript"]))})
    for n, f in enumerate(broll, 1):
        sources.append({"id": f"b{n}", "path": str(f).replace("\\", "/"), "kind": "broll", "dur": duration(f)})
    shortsapp.save_raw(work, name, {"mode": "raw", "folder": str(folder).replace("\\", "/"), "source": sources[0]["path"], "transcript": sources[0]["transcript"],
                                    "speakers": "", "sources": sources, "shorts": []})


# ----------------------------------------------------------------------------- the prompt
RULES = """You are making YouTube Shorts for the channel from RAW footage: recordings of the host talking (some with several takes of the same line, restarts and mistakes) and b-roll clips. There is no finished video.
The goal: views, from fast, complete little stories told by the host.

How many: at most {count} short{plural}. Fewer is fine when the footage holds fewer good ones.

Rules (the host's):
- Each short is a COMPLETE THOUGHT of {min_s} to {max_s} seconds of the host talking (favour under a minute): a setup, a point and a payoff. State all three in "thought".
- A short is a list of ranges in play order. A range is {{"src": a talking recording's id, "a": seconds, "b": seconds}}. Take the BEST take of every line: when the host says the same thing more than once, use the last clean one and never an abandoned or restarted take. Ranges may come from different recordings, joined by cuts. Never change what the host said.
- Passages marked [restart/repeat: ... ] in the transcript are mistakes the app cuts out by itself; you may include a range that holds one, but prefer a range that starts after it.
- Start on the hook (the interesting claim or question), never on "so", "and" or an unfinished thought. End on the payoff, after a sentence ends. A later pass tightens filler.
- hook = the title shown over the first {hook_s} seconds: 2 to 5 words, uppercase, max 3 lines separated with |, a promise or a question, no clickbait lies.
- B-roll: lay a clip over words with an overlay {{"src": a b-roll id, "a": seconds into the clip, "b": seconds, "at": {{"src": a talking recording's id, "t": the second of the word it comes in at}}, "why": one line}}. The host's voice keeps going; only the picture changes. Each runs {omin} to {omax} seconds, about one per six seconds of the short, only where the clip shows what is being said (look at its picture: read the image file named for it). Never over the first two seconds. Do not use a clip twice in one short. If no clip fits, use none.
- If the short would be much better with a line the host did not record, say so in "missing" (one sentence, what to say). Do not rely on it.

Write the result to candidates.json in the current folder (use the Write tool), exactly this shape and nothing else, best first:
[{{"title": "...", "hook": "...", "why": "one sentence", "thought": {{"setup": "...", "point": "...", "payoff": "..."}}, "ranges": [{{"src": "t1", "a": 12.0, "b": 31.5}}], "overlays": [{{"src": "b1", "a": 0.0, "b": 3.0, "at": {{"src": "t1", "t": 14.2}}, "why": "..."}}], "missing": ""}}]
Times are each recording's own seconds, taken from the transcript lines below: the start of the first word you keep and the end of the last word you keep.
"""


def _line(s, bad):
    mark = " [restart/repeat: cut out automatically]" if any(a - 0.05 <= s["start"] and s["end"] <= b + 0.05 for a, b in bad) else ""
    return f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}{mark}"


def prompt(work: str, name: str, count: int | None = None) -> str:
    cfg = sh.load(shortsapp.cfg_file(work, name))
    r = skillrules.shorts()
    count = count or r["raw_max_shorts"]
    head = RULES.format(count=count, plural="" if count == 1 else "s", min_s=r["min_s"], max_s=r["max_s"], hook_s=r["hook_s"], omin=r["overlay_min_s"], omax=r["overlay_max_s"])
    raw = shortsapp.read_raw(work, name)
    parts, fd = [], WORK / work / "shorts" / "_find"
    for sp in raw["sources"]:
        s = cfg["_srcs"][sp["id"]]
        if sp["kind"] == "talk":
            lines = "\n".join(_line(x, sp.get("mistakes") or []) for x in s["tr"]["segments"])
            parts.append(f"TALKING RECORDING {sp['id']} ({Path(sp['path']).name}, {s['tr'].get('duration', 0):.0f} s):\n{lines}")
        else:
            img = fd / "broll" / f"{sp['id']}.jpg"
            seen = f"picture: broll/{sp['id']}.jpg" if contact_sheet(sp["path"], img) else "picture unavailable"
            parts.append(f"B-ROLL {sp['id']} ({Path(sp['path']).name}, {sp.get('dur') or 0:.1f} s, {seen})")
    have = [f"{s['title']}" for s in raw.get("shorts", [])]
    extra = ("\nShorts that already exist (do not repeat these):\n- " + "\n- ".join(have) + "\n") if have else ""
    return head + extra + "\n" + "\n\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- checking and importing the answer
def _inside(spans, a, b) -> float:
    """Seconds of [a, b] that lie in any of the spans."""
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


def check(cand: dict, sources: dict) -> tuple:
    """(the short with its ranges and overlays made clean or None, [problems that stop it], [overlays left out and why])."""
    r = skillrules.shorts()
    problems, left = [], []
    ranges = []
    for x in cand.get("ranges") or []:
        try:
            src, a, b = x["src"], float(x["a"]), float(x["b"])
        except (KeyError, TypeError, ValueError):
            problems.append("a range needs src, a and b")
            continue
        sp = sources.get(src)
        if not sp or sp["kind"] != "talk":
            problems.append(f"{src} is not a talking recording")
        elif not 0 <= a < b <= float(sp["dur"]) + 0.5:
            problems.append(f"{src} {a}-{b} is outside the recording ({sp['dur']:.0f} s)")
        elif _inside(sp.get("mistakes") or [], a, b) > 0.6 * (b - a):
            problems.append(f"{src} {a:.0f}-{b:.0f} is a take the host abandoned")
        else:
            ranges.append({"src": src, "a": round(a, 2), "b": round(min(b, float(sp["dur"])), 2)})
    if not ranges:
        return None, problems or ["no ranges"], left
    total = sum(x["b"] - x["a"] for x in ranges)
    if total < r["min_s"]:
        problems.append(f"{total:.0f} s is under the {r['min_s']:.0f} s minimum")
    if total > r["max_s"]:
        problems.append(f"{total:.0f} s is over the {r['max_s']:.0f} s maximum")
    for i, x in enumerate(ranges):
        for y in ranges[i + 1:]:
            if x["src"] == y["src"] and min(x["b"], y["b"]) - max(x["a"], y["a"]) > 0.1:
                problems.append("two ranges play the same part")
    th = cand.get("thought") or {}
    if not all(str(th.get(k, "")).strip() for k in ("setup", "point", "payoff")):
        problems.append("it must state its setup, point and payoff (a complete thought)")
    if problems:
        return None, problems, left
    overlays, used = [], set()
    for o in cand.get("overlays") or []:
        try:
            src, a, b = o["src"], float(o["a"]), float(o["b"])
            at = {"src": o["at"]["src"], "t": round(float(o["at"]["t"]), 2)}
        except (KeyError, TypeError, ValueError):
            left.append("an overlay needs src, a, b and at")
            continue
        sp = sources.get(src)
        if not sp or sp["kind"] != "broll":
            left.append(f"{src} is not a b-roll clip")
        elif src in used:
            left.append(f"{src} is used twice")
        elif not 0 <= a < b <= float(sp["dur"]) + 0.3:
            left.append(f"{src} {a}-{b} is outside the clip ({sp['dur']:.1f} s)")
        elif b - a < r["overlay_min_s"]:
            left.append(f"{src} is under {r['overlay_min_s']:g} s")
        elif not any(x["src"] == at["src"] and x["a"] <= at["t"] <= x["b"] for x in ranges):
            left.append(f"{src} comes in at a word that is not in the short")
        elif at["t"] - ranges[0]["a"] < 2.0 and at["src"] == ranges[0]["src"]:
            left.append(f"{src} would cover the first two seconds")
        else:
            used.add(src)
            overlays.append({"src": src, "a": round(a, 2), "b": round(min(b, a + r["overlay_max_s"], float(sp["dur"])), 2), "at": at, "why": str(o.get("why", ""))[:200]})
    return dict(cand, ranges=ranges, overlays=overlays), problems, left


def _shared(a: list, b: list) -> float:
    return sum(max(0.0, min(x["b"], y["b"]) - max(x["a"], y["a"])) for x in a for y in b if x["src"] == y["src"])


def import_candidates(work: str, name: str, path: Path, count: int | None = None) -> int:
    """Add Claude's shorts that pass `check` (what was left out, and why, is kept in raw['last_find']). Each short also gets the mistakes inside its ranges as `drop`."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    raw = shortsapp.read_raw(work, name)
    cfg = sh.load(shortsapp.cfg_file(work, name))
    sources = {sp["id"]: dict(sp, dur=cfg["_srcs"][sp["id"]]["tr"].get("duration") or sp.get("dur") or 0) for sp in raw["sources"]}
    ids = [int(m.group(1)) for s in raw.get("shorts", []) if (m := re.match(r"^s(\d+)$", s["id"]))]
    n = max(ids, default=0)
    kept = [s["ranges"] for s in raw.get("shorts", []) if shortsapp.status_of(s) != "dropped"]
    limit = count or skillrules.shorts()["raw_max_shorts"]
    added, skipped = 0, []
    for c in data if isinstance(data, list) else []:
        title = str(c.get("title", "Short"))[:90]
        if added >= limit:
            skipped.append(f"{title}: more than the {limit} asked for")
            continue
        clean, problems, left = check(c, sources)
        if clean is None:
            skipped.append(f"{title}: {problems[0]}")
            continue
        if any(_shared(clean["ranges"], k) / max(1.0, sum(x["b"] - x["a"] for x in clean["ranges"])) > 0.25 for k in kept if k and isinstance(k[0], dict)):
            skipped.append(f"{title}: the same part as another short")
            continue
        drop = [{"src": x["src"], "a": a, "b": b} for x in clean["ranges"] for a, b in sources[x["src"]].get("mistakes") or [] if min(b, x["b"]) - max(a, x["a"]) > 0.05]
        n += 1
        added += 1
        kept.append(clean["ranges"])
        why = str(c.get("why", ""))[:300] + (f" Missing: {c['missing']}"[:200] if str(c.get("missing", "")).strip() else "")
        raw.setdefault("shorts", []).append({"id": f"s{n}", "title": title, "hook": str(c.get("hook", ""))[:90].upper(), "why": why.strip(),
                                             "thought": {k: str((c.get("thought") or {}).get(k, ""))[:300] for k in ("setup", "point", "payoff")},
                                             "status": "", "ranges": clean["ranges"], "overlays": clean["overlays"], "drop": drop})
        if left:
            skipped.append(f"{title}: b-roll left out ({'; '.join(left)})")
    raw["last_find"] = {"asked": count, "added": added, "skipped": skipped, "at": time.time()}
    shortsapp.save_raw(work, name, raw)
    return added
