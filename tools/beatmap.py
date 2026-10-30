"""Beat map: what is said and what is on screen, beat by beat (stage 3 of the video workflow).

Usage:
    python beatmap.py build  <work> <name>     # starter map from the script + the takes picked in the Clips tab
    python beatmap.py resync <work> <name>     # take the latest takes again, keep the plan Claude and the host wrote
    python beatmap.py check  <work> <name>     # print the risks

<name>.beatmap.json:
  {"version": 1, "generated", "beats": [beat], "orphans": [...], "changes": [...]}
  beat = {"id": "B01", "section", "script_lines": ["S01"], "said": "the real words", "missing": false,
          "aroll": {"rel", "in", "out", "dur", "span", "span_in", "span_out", "keep": [[a, b], ...] | null, "trim_by", "words": [[w, a, b], ...]} | null,
                   "start", "end" (estimated output seconds),
          "on_screen": {"shot": "a-roll|punch-in|b-roll|screenshot|graphic|text", "note": "",
                        "broll": [{"file", "in", "dur", "why"}]},
          "graphic": null | {"kind": "explainer|ui|stamp|counter|burst|3d|kinetic|title|end", "style", "idea",
                             "words": "the words it is timed to", "dur": seconds, "text": "on-screen copy",
                             "strength": 1-5, "why", "struck": false},
          "audio": {"music": "", "sfx": []}, "why": "", "cut_if": "", "user_note": "", "skip": false, "flags": []}

Claude fills on_screen / graphic / audio / why / cut_if with judgment (keep graphics few; every one needs a
reason, the words it is timed to and a strength rating so the weakest can be offered for cutting). The host strikes or
edits in the Beat map tab. Each build saves the beat map it starts from (snapshot_for_build) as <name>.beatmap.v<N>.json; the Beat map tab shows what changed since.
Voice-over beats (id TP01...): {"vo": {"id", "file", "start", "end", "after": "S08", "words": [[w, a, b]]}, "aroll": null, ...}: the picture is the
first B-roll insert (it plays the voice-over's length), the sound is the voice-over take, the graphic runs the same length. They sit after the beat that
covers the line in `vo.after` and are kept by "Update from clips".
Trims: the matched take often holds more than the beat uses (chatter, a restart, a sentence that stops short). <name>.trims.json
remembers which words each beat keeps ({"entries": {"<span>|S01,S02": {"keep": [[a, b], ...], "by", "at"}}}, source seconds); the
starter lays them back on every rebuild, so "Update from clips" never loses them. `aroll.words` is the take's words around the
matched span (5 s before, 20 s after) so the tab can show them; `keep` is null while the whole span plays.
Python stdlib only.
"""
import argparse
import copy
import json
import math
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
import config
WORK = config.WORK
sys.path.insert(0, str(HERE))
import clipmap  # noqa: E402
import workflow  # noqa: E402

KINDS = ("explainer", "ui", "stamp", "counter", "burst", "3d", "kinetic", "title", "end")
CARDS = ("title", "end")
POPUPS = ("counter", "stamp", "burst", "kinetic")   # small on-screen pop-ups and text: they do not use the motion-graphic budget
SHOTS = ("a-roll", "punch-in", "b-roll", "screenshot", "graphic", "text")
STRETCH_MAX = 30.0          # s of plain A-roll before the 15-30 s visual-change guideline is broken
WPS_GUESS = 2.75            # words per second for lines nobody has recorded yet
TRIM_LEAD, TRIM_TAIL, TRIM_GAP = 0.08, 0.18, 0.02   # s of breath kept before / after a kept run of words, and the least left to a dropped neighbour
TRIM_DEAD = 1.5                                     # a silence longer than this inside a kept stretch is cut (dead air)
WIN_BEFORE, WIN_AFTER = 15.0, 20.0                   # s of the take shown around the matched span so a trim can reach a sentence that stops short


def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def path_of(work: str, name: str) -> Path:
    return WORK / work / f"{name}.beatmap.json"


def settings_of(work: str, name: str) -> dict:
    return {**workflow.DEFAULT_SETTINGS, **workflow.load(work, name)["settings"]}


# ----------------------------------------------------------------------------- build
def blank_beat(bid, section, lines, said, aroll, dur, missing, flags):
    return {"id": bid, "section": section, "script_lines": lines, "said": said, "missing": missing, "aroll": aroll,
            "dur": round(dur, 2), "start": 0.0, "end": 0.0,
            "on_screen": {"shot": "a-roll", "note": "", "broll": []}, "graphic": None,
            "audio": {"music": "", "sfx": []}, "why": "", "cut_if": "", "user_note": "", "skip": False, "flags": flags}


# ----------------------------------------------------------------------------- trims (which words of a take a beat keeps)
def trims_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.trims.json"


def trim_key(span: str, lines: list[str]) -> str:
    return f"{span}|{','.join(lines)}"


def read_trims(work: str, name: str) -> dict:
    return (read_json(trims_path(work, name), None) or {}).get("entries", {})


def write_trims(work: str, name: str, entries: dict):
    write_json(trims_path(work, name), {"version": 1, "entries": entries})


def keep_from_idx(words: list, idx, dead: float | None = None) -> list[list[float]]:
    """Source-second ranges for the kept words (positions in `words`): each run of neighbouring words gets a little breath
    either side, never closer than TRIM_GAP to a dropped neighbour; runs that end up touching are joined. A pause over `dead` (TRIM_DEAD) splits a run."""
    idx = sorted(set(idx))
    runs, cur = [], []
    for i in idx:
        if cur and i == cur[-1] + 1 and words[i][1] - words[i - 1][2] <= (TRIM_DEAD if dead is None else dead):
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = [i]
    if cur:
        runs.append(cur)
    out = []
    for r in runs:
        lead, tail = TRIM_LEAD, TRIM_TAIL
        if r[0] > 0:                                            # a word we are cutting sits close before: no breath at all (word times are only good to about 0.2 s)
            lead = min(lead, max(0.0, words[r[0]][1] - words[r[0] - 1][2] - 0.2))
        if r[-1] + 1 < len(words):                              # the same after: The creator heard the start of a cut "and" at the end of a line (2026-10-25)
            tail = min(tail, max(0.0, words[r[-1] + 1][1] - words[r[-1]][2] - 0.2))
        a, z = max(words[r[0]][1] - lead, 0.0), words[r[-1]][2] + tail
        if out and a <= out[-1][1] + 0.01:
            out[-1][1] = round(z, 3)
        else:
            out.append([round(a, 3), round(z, 3)])
    return out


def kept_flags(words: list, keep) -> list[bool]:
    return [any(a - 0.001 <= (w[1] + w[2]) / 2 <= b + 0.001 for a, b in keep) for w in words]


def kept_text(words: list, keep) -> str:
    return " ".join(w[0] for w, k in zip(words, kept_flags(words, keep)) if k)


def apply_keep(ar: dict, keep, by: str = "user"):
    """Narrow an aroll to the kept ranges (keep=None puts the whole matched span back)."""
    if keep:
        ar.update(keep=keep, **{"in": keep[0][0], "out": keep[-1][1]}, dur=round(sum(b - a for a, b in keep), 2), trim_by=by)
    else:
        ar.update(keep=None, **{"in": ar["span_in"], "out": ar["span_out"]}, dur=round(ar["span_out"] - ar["span_in"], 2))
        ar.pop("trim_by", None)


def starter(work: str, name: str) -> list[dict]:
    script = clipmap.load_script(work, name)
    clips = read_json(WORK / work / f"{name}.clips.json")
    if not clips:
        raise ValueError("no clips.json yet: match the takes to the script in the Clips tab first")
    analysis = (read_json(WORK / work / f"{name}.footage.json", None) or {}).get("analysis") or {}
    trims = read_trims(work, name)
    spans = {sp["id"]: (c["rel"], sp) for c in clips["clips"] for sp in c["spans"]}
    lines, by_line = script.lines, clips.get("by_line", {})
    beats, k = [], 0
    while k < len(lines):
        ln = lines[k]
        sid = (by_line.get(ln["id"]) or {}).get("picked")
        group = [ln]
        if sid:
            while k + len(group) < len(lines) and (by_line.get(lines[k + len(group)]["id"]) or {}).get("picked") == sid:
                group.append(lines[k + len(group)])
        k += len(group)
        ids = [g["id"] for g in group]
        bid = f"B{len(beats) + 1:02d}"
        if sid and sid in spans:
            rel, sp = spans[sid]
            allw = (analysis.get(rel) or {}).get("list") or []
            ar = {"rel": rel, "in": sp["start"], "out": sp["end"], "dur": sp["dur"], "span": sid, "span_in": sp["start"], "span_out": sp["end"], "keep": None,
                  "words": [w for w in allw if w[2] >= sp["start"] - WIN_BEFORE and w[1] <= sp["end"] + WIN_AFTER]}
            said = sp["text"]
            ent = trims.get(trim_key(sid, ids))
            if ent and ent.get("keep") and ar["words"]:
                apply_keep(ar, ent["keep"], ent.get("by", "user"))
                said = kept_text(allw, ent["keep"]) or said                # the whole take, not only the shown window: a kept piece can lie far from the matched span
            beats.append(blank_beat(bid, ln["heading"] or "", ids, said, ar, ar["dur"], False, list(sp.get("flags", []))))
        else:
            words = sum(len(g["tokens"]) for g in group)
            beats.append(blank_beat(bid, ln["heading"] or "", ids, "[not recorded] " + " ".join(g["said"] for g in group),
                                    None, words / WPS_GUESS, True, ["no footage for this line yet"]))
    return beats


def retime(beats: list[dict]):
    t = 0.0
    for b in beats:
        b["start"] = round(t, 2)
        if not b.get("skip"):
            t += b["dur"]
        b["end"] = round(t, 2)


def build(work: str, name: str) -> dict:
    p = path_of(work, name)
    if p.exists():
        raise ValueError("a beat map already exists: use 'Update from clips' to keep your plan")
    beats = starter(work, name)
    retime(beats)
    data = {"version": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "beats": beats, "orphans": [], "changes": []}
    write_json(p, data)
    return data


def resync(work: str, name: str, confirm: bool = False) -> dict:
    """Take the newest takes/timings from clips.json; keep every plan field on beats that still cover the same
    script lines. A beat whose lines changed loses its plan: any graphic is parked in `orphans`."""
    p = path_of(work, name)
    old = read_json(p)
    if not old:
        raise ValueError("no beat map yet")
    new = starter(work, name)
    keep = ("on_screen", "graphic", "audio", "why", "cut_if", "user_note", "skip")
    vo_beats = [b for b in old["beats"] if b.get("vo")]                   # voice-over beats are not made from takes: keep them where they were
    by_lines = {tuple(b["script_lines"]): b for b in old["beats"] if not b.get("vo")}
    used = set()
    for b in new:
        o = by_lines.get(tuple(b["script_lines"]))
        if o:
            used.add(tuple(b["script_lines"]))
            for k in keep:
                b[k] = o[k]
            b["id"] = o["id"]                                      # a beat keeps its id (storyboard marks, built graphics, notes and the graphics plan are keyed by it)
    old["orphans"] = old.get("orphans", []) + [
        {"was": o["id"], "script_lines": o["script_lines"], "graphic": o.get("graphic"), "why": o.get("why"), "user_note": o.get("user_note")}
        for key, o in by_lines.items() if key not in used and (o.get("graphic") or o.get("user_note"))]
    taken = {b["id"] for b in old["beats"]}
    nxt = max([int(i[1:]) for i in taken if i[:1] == "B" and i[1:].isdigit()] + [0])
    for b in new:                                                  # a beat that is new gets a number nobody has used
        if tuple(b["script_lines"]) not in by_lines:
            nxt += 1
            b["id"] = f"B{nxt:02d}"
    old_pos = {tuple(b["script_lines"]): i for i, b in enumerate(old["beats"]) if not b.get("vo")}      # keep the order the beats are in now (the creator may have moved one)
    ordered = sorted((b for b in new if tuple(b["script_lines"]) in old_pos), key=lambda b: old_pos[tuple(b["script_lines"])])
    prev = None
    for b in new:                                                                               # a beat that is new goes after the beat before it in the script
        if tuple(b["script_lines"]) in old_pos:
            prev = b
            continue
        ordered.insert(ordered.index(prev) + 1 if prev is not None else 0, b)
        prev = b
    new = ordered
    for vb in vo_beats:
        at = next((i for i, x in enumerate(new) if vb["vo"].get("after") in x["script_lines"]), None)
        new.insert(at + 1 if at is not None else len(new), vb)
    old["beats"] = new
    retime(old["beats"])
    old["changes"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "app", "what": "updated from the latest takes",
                           "beats_kept": len(used), "beats_new": len(new) - len(used)})
    write_json(p, old)
    return old


# ----------------------------------------------------------------------------- stats and checks
def is_card(g) -> bool:
    return bool(g) and g.get("kind") in CARDS


def is_popup(g) -> bool:
    return bool(g) and g.get("kind") in POPUPS


def is_explainer(g) -> bool:
    """A motion-graphic explainer (the ones the graphics budget is for): not a title/end card, not a pop-up."""
    return bool(g) and not is_card(g) and not is_popup(g)


def live_graphic(b) -> dict | None:
    g = b.get("graphic")
    return g if g and not g.get("struck") and not b.get("skip") else None


def changes_picture(b) -> bool:
    return b["on_screen"].get("shot", "a-roll") != "a-roll" or bool(live_graphic(b)) or bool(b["on_screen"].get("broll"))


def stats(data: dict, settings: dict) -> dict:
    beats = [b for b in data["beats"] if not b.get("skip")]
    runtime = sum(b["dur"] for b in beats)
    gfx = [live_graphic(b) for b in beats if live_graphic(b)]
    body = [g for g in gfx if is_explainer(g)]
    budget = math.ceil(runtime / 60 * settings["graphics_per_minute"]) if runtime else 0
    return {"runtime_s": round(runtime, 1), "beats": len(beats), "skipped": len(data["beats"]) - len(beats),
            "graphics": len(body), "popups": sum(1 for g in gfx if is_popup(g)), "cards": sum(1 for g in gfx if is_card(g)), "budget": budget,
            "struck": sum(1 for b in data["beats"] if b.get("graphic") and b["graphic"].get("struck")),
            "broll": sum(len(b["on_screen"].get("broll", [])) for b in beats),
            "punch_ins": sum(1 for b in beats if b["on_screen"].get("shot") == "punch-in"),
            "music": len({b["audio"]["music"] for b in beats if b["audio"].get("music")}),
            "sfx": sum(len(b["audio"].get("sfx", [])) for b in beats),
            "missing": sum(1 for b in beats if b.get("missing")),
            "trimmed": sum(1 for b in beats if (b.get("aroll") or {}).get("keep"))}


def weakest(data: dict, n: int) -> list[str]:
    """Beat ids of the n weakest motion explainers (lowest strength; ties: longest first)."""
    cands = [(live_graphic(b).get("strength") or 3, -(live_graphic(b).get("dur") or 0), b["id"])
             for b in data["beats"] if is_explainer(live_graphic(b))]
    return [c[2] for c in sorted(cands)[:max(0, n)]]


def reading_budget(text: str, settings: dict) -> float:
    return max(settings["min_visible_s"], len(text.split()) * settings["read_s_per_word"]) + settings["read_pad_s"]


REDUNDANT_STOP = set("the a an and of to in it is was i that this so but my for on with as be at".split())


def repeated_phrases(data: dict, min_shared: int = 2) -> list[tuple]:
    """Pairs of beats that say nearly the same thing: [(first beat, later beat, shared 4-word runs, an example)]. The host (2026-10-25): watch for redundant phrases."""
    import collections
    grams = collections.defaultdict(set)
    for b in data["beats"]:
        if b.get("skip"):
            continue
        t = re.findall(r"[a-z0-9']+", (b.get("said") or "").lower())
        for i in range(len(t) - 3):
            g = tuple(t[i:i + 4])
            if sum(1 for w in g if w not in REDUNDANT_STOP) >= 2:
                grams[g].add(b["id"])
    order = {b["id"]: i for i, b in enumerate(data["beats"])}
    pairs, ex = collections.Counter(), {}
    for g, ids in grams.items():
        ids = sorted(ids, key=lambda x: order[x])
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs[(ids[i], ids[j])] += 1
                ex.setdefault((ids[i], ids[j]), " ".join(g))
    return [(a, b, n, ex[(a, b)]) for (a, b), n in pairs.most_common() if n >= min_shared]


def check(data: dict, settings: dict, script_ids: list[str] | None = None) -> list[dict]:
    """Risks to look at before approval: [{beat, level: fix|look, text}]. These are the checks the workflow asks
    Claude to run on the plan; the self-review repeats the timing ones on the rendered video."""
    out = []
    add = lambda beat, level, text: out.append({"beat": beat, "level": level, "text": text})
    st = stats(data, settings)
    if st["graphics"] > st["budget"]:
        over = st["graphics"] - st["budget"]
        add(None, "look", f"{st['graphics']} motion explainers is {over} over your budget of {st['budget']} for {st['runtime_s'] / 60:.1f} min: "
                          f"weakest to cut first: {', '.join(weakest(data, over))}")
    for a, b2, n, eg in repeated_phrases(data):
        add(b2, "look", f"says nearly the same as {a} (“…{eg}…”, {n} shared phrases): is one of them redundant?")
    covered = {l for b in data["beats"] for l in b["script_lines"]}
    for lid in (script_ids or []):
        if lid not in covered:
            add(None, "fix", f"script line {lid} is in no beat")
    run, run_from = 0.0, None
    for b in data["beats"]:
        if b.get("skip"):
            continue
        if b.get("missing"):
            add(b["id"], "fix", f"no footage yet for {', '.join(b['script_lines'])}")
        if b.get("flags") and not b.get("missing"):
            add(b["id"], "look", "take: " + "; ".join(b["flags"]))
        g = live_graphic(b)
        if g:
            for f in ("idea", "words", "why"):
                if not g.get(f):
                    add(b["id"], "fix", f"graphic has no {'reason' if f == 'why' else f}")
            d = g.get("dur") or 0
            if d and d < settings["min_visible_s"]:
                add(b["id"], "fix", f"graphic is on screen {d:.1f} s: shorter than {settings['min_visible_s']:.1f} s will flash")
            if g.get("text") and d and d < reading_budget(g["text"], settings):
                add(b["id"], "fix", f"text “{g['text'][:40]}” needs {reading_budget(g['text'], settings):.1f} s to read, graphic gives {d:.1f} s")
            if d and d > b["dur"] + 1.0 and not is_card(g):
                add(b["id"], "look", f"graphic ({d:.1f} s) outlasts its beat ({b['dur']:.1f} s)")
            if not g.get("strength"):
                add(b["id"], "look", "graphic has no strength rating (1-5), so it cannot be ranked for cutting")
        for br in b["on_screen"].get("broll", []):
            if not br.get("file") or not br.get("why"):
                add(b["id"], "fix", "B-roll insert needs a file and a reason")
        if not (b.get("why") or "").strip() and (g or b["on_screen"].get("shot") != "a-roll" or b["on_screen"].get("broll")):
            add(b["id"], "fix", "this beat changes the picture but has no written reason")
        if changes_picture(b):
            run, run_from = 0.0, None
        else:
            run_from = run_from or b["id"]
            run += b["dur"]
            if run > STRETCH_MAX:
                add(b["id"], "look", f"{run:.0f} s of plain A-roll since {run_from}: look for B-roll, a punch-in or a graphic that earns its place")
                run, run_from = 0.0, None
    return out


# ----------------------------------------------------------------------------- freezing and versions
def snapshot_for_build(work: str, name: str):
    """Save the beat map a build starts from as <name>.beatmap.v<N>.json; the Beat map tab shows what changed since."""
    data = read_json(path_of(work, name))
    if data:
        write_json(path_of(work, name).with_name(f"{name}.beatmap.v{data.get('version', 1)}.json"), data)


def latest_snapshot(work: str, name: str):
    snaps = sorted(path_of(work, name).parent.glob(f"{name}.beatmap.v*.json"),
                   key=lambda p: int(re.search(r"\.v(\d+)\.json$", p.name).group(1)))
    return read_json(snaps[-1]) if snaps else None


def diff_vs_build(work: str, name: str, data: dict) -> dict | None:
    prev = latest_snapshot(work, name)
    if not prev:
        return None
    a, b = {x["id"]: x for x in prev["beats"]}, {x["id"]: x for x in data["beats"]}
    strip = lambda x: {k: v for k, v in x.items() if k not in ("start", "end")}
    return {"from": prev.get("version", 1), "changed": [i for i in b if i in a and strip(a[i]) != strip(b[i])],
            "added": [i for i in b if i not in a], "removed": [i for i in a if i not in b]}


# ----------------------------------------------------------------------------- edits
BEAT_FIELDS = {"why": str, "cut_if": str, "user_note": str, "skip": bool}
PATHS = {
    "on_screen.shot": lambda v: v if v in SHOTS else _bad(f"shot must be one of {', '.join(SHOTS)}"),
    "on_screen.note": str, "audio.music": str,
    "audio.sfx": lambda v: [s.strip() for s in (v.split("\n") if isinstance(v, str) else v) if str(s).strip()],
    "graphic.struck": bool, "graphic.kind": lambda v: v if v in KINDS else _bad(f"kind must be one of {', '.join(KINDS)}"),
    "graphic.style": str, "graphic.idea": str, "graphic.words": str, "graphic.text": str, "graphic.why": str,
    "graphic.place": lambda v: v if v in ("", "auto", "full", "left35", "right35", "bl33") else _bad("place must be auto, full, left35, right35 or bl33"),
    "graphic.draft": str,           # path of a draft still (PNG with alpha is best) the storyboard places over the frame
    "graphic.dur": lambda v: round(max(0.0, float(v)), 2), "graphic.strength": lambda v: min(5, max(1, int(v))),
}


def _bad(msg):
    raise ValueError(msg)


def find_beat(data, bid):
    b = next((x for x in data["beats"] if x["id"] == bid), None)
    if not b:
        raise ValueError(f"unknown beat {bid!r}")
    return b


def apply_edit(work: str, name: str, b: dict) -> dict:
    """b = {beat, set: {path: value}, confirm?, why?}. Paths are whitelisted (PATHS and BEAT_FIELDS)."""
    p = path_of(work, name)
    data = read_json(p)
    if not data:
        raise ValueError("no beat map yet")
    beat = find_beat(data, b["beat"])
    sets = b.get("set") or {}
    if not sets:
        return data
    before = copy.deepcopy(data)
    changed = {}
    for path, val in sets.items():
        if path in BEAT_FIELDS:
            new = BEAT_FIELDS[path](val) if BEAT_FIELDS[path] is not bool else bool(val)
            if beat.get(path) != new:
                changed[path] = [beat.get(path), new]
                beat[path] = new
        elif path in PATHS:
            head, key = path.split(".")
            conv = PATHS[path]
            new = bool(val) if conv is bool else conv(val)
            if head == "graphic" and not beat.get("graphic"):
                beat["graphic"] = {"kind": "explainer", "struck": False}
            cur = beat[head].get(key) if beat.get(head) else None
            if cur != new:
                changed[path] = [cur, new]
                beat[head][key] = new
        else:
            raise ValueError(f"cannot edit {path!r}")
    if not changed:
        return before                                # a no-op never makes a new version
    retime(data["beats"])
    entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "user", "beat": beat["id"], "set": changed}
    if b.get("why"):
        entry["why"] = b["why"]
    data["changes"].append(entry)
    write_json(p, data)
    return data


def apply_trim(work: str, name: str, b: dict) -> dict:
    """b = {beat, kept: [positions in aroll.words] | reset: true, confirm?, why?}. Stores the choice in trims.json (so it survives
    'Update from clips') and narrows the beat; on an approved beat map this is a new version like any other edit."""
    p = path_of(work, name)
    data = read_json(p)
    if not data:
        raise ValueError("no beat map yet")
    beat = find_beat(data, b["beat"])
    a = beat.get("aroll")
    if not a or not a.get("words"):
        raise ValueError("this beat has no take to trim")
    words = a["words"]
    if b.get("reset"):
        keep = None
    else:
        idx = [int(i) for i in b.get("kept") or [] if 0 <= int(i) < len(words)]
        if not idx:
            raise ValueError("keep at least one word (or tick 'leave this beat out')")
        keep = keep_from_idx(words, idx)
    if keep == a.get("keep"):
        return data
    a = find_beat(data, b["beat"])["aroll"]
    key = trim_key(a["span"], beat["script_lines"])
    entries = read_trims(work, name)
    if keep:
        entries[key] = {"keep": keep, "by": "user", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    else:
        entries.pop(key, None)
    write_trims(work, name, entries)
    apply_keep(a, keep, "user")
    beat["said"] = kept_text(words, keep) if keep else " ".join(w[0] for w in words if w[1] >= a["span_in"] - 0.001 and w[2] <= a["span_out"] + 0.001)
    beat["dur"] = a["dur"]
    retime(data["beats"])
    entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "user", "beat": beat["id"],
             "what": f"{beat['id']} trimmed to {a['dur']:.1f} s" if keep else f"{beat['id']} trim removed"}
    if b.get("why"):
        entry["why"] = b["why"]
    data["changes"].append(entry)
    write_json(p, data)
    return data


def strike(work: str, name: str, ids: list[str], struck: bool, why: str = "", confirm: bool = False) -> dict:
    p = path_of(work, name)
    data = read_json(p)
    if not data:
        raise ValueError("no beat map yet")
    targets = [find_beat(data, i) for i in ids]
    targets = [t for t in targets if t.get("graphic") and bool(t["graphic"].get("struck")) != struck]
    if not targets:
        return data
    for t in targets:
        t["graphic"]["struck"] = struck
    retime(data["beats"])
    entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "user", "beats": [t["id"] for t in targets],
             "what": "cut graphics" if struck else "restored graphics"}
    if why:
        entry["why"] = why
    data["changes"].append(entry)
    write_json(p, data)
    return data


# ----------------------------------------------------------------------------- state for the app
def state(work: str, name: str) -> dict:
    p = path_of(work, name)
    st = settings_of(work, name)
    out = {"exists": p.exists(), "settings": st, "data": None, "stats": None, "risks": [],
           "weakest": [], "diff": None, "clips_ready": (WORK / work / f"{name}.clips.json").exists(),
           "script_ready": (WORK / work / f"{name}.script.md").exists()}
    if not p.exists():
        return out
    data = read_json(p)
    try:
        ids = [ln["id"] for ln in clipmap.load_script(work, name).lines]
    except ValueError:
        ids = []
    s = stats(data, st)
    out.update(data=data, stats=s, risks=check(data, st, ids), diff=diff_vs_build(work, name, data),
               weakest=weakest(data, max(0, s["graphics"] - s["budget"]) or 3))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "resync", "check"])
    ap.add_argument("work")
    ap.add_argument("name")
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            d = build(a.work, a.name)
        elif a.cmd == "resync":
            d = resync(a.work, a.name)
        else:
            d = read_json(path_of(a.work, a.name))
            if not d:
                sys.exit("no beat map yet")
    except ValueError as e:
        sys.exit(f"beatmap: {e}")
    st = settings_of(a.work, a.name)
    s = stats(d, st)
    print(f"{s['beats']} beats, {s['runtime_s'] / 60:.1f} min, {s['graphics']} motion explainers (budget {s['budget']}) + {s['popups']} pop-ups + {s['cards']} cards, "
          f"{s['broll']} B-roll, {s['punch_ins']} punch-ins, {s['missing']} beats without footage")
    for r in check(d, st):
        print(f"  [{r['level']}] {r['beat'] or 'all'}: {r['text']}")


if __name__ == "__main__":
    main()
