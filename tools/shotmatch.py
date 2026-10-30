"""What we have for each shot (ADR 0007, phase 5): the outline's [VISUAL] lines matched to real footage, with the gaps flagged.

A shot idea is either the host on camera ("Cut to A-Roll": the take of his words is the picture) or something to show (B-roll, a screen recording).
The second kind is looked up in the vision library (brolllib.search: free, local, finds clips by what they show, so a clip with no speech works);
Claude is only asked to pick among the best few when there are several. `<name>.shots.json` (a plan file) keeps the answer per shot:
  {"shots": {"<key>": {"visual", "section", "chosen": {rel, t, dur, score, what} | null, "candidates": [..], "by": "auto|claude|user"}}}
The key is a hash of the section and the shot idea's words, so editing the outline keeps the matches of the lines that did not change.
`apply_to_beats` puts the chosen clip under the spoken line as a B-roll cutaway, without touching a cutaway somebody placed by hand.
"""
import difflib
import json
import re
from pathlib import Path

import brolllib
import config
import outline
import projectstore
import skillrules

WORK = config.WORK
THRESH = 1.0                 # a combined search score at or above this is a likely match (real footage: right clips 2 to 4, wrong ones below 0)
TOP = 4
FILLER = {"b", "roll", "broll", "cut", "showing", "shows", "show", "montage", "close", "up", "screen", "recording", "of", "fast", "paced"}


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.shots.json"


def load(work: str, name: str) -> dict:
    try:
        return json.loads(path(work, name).read_text(encoding="utf-8-sig")).get("shots", {})
    except (OSError, ValueError):
        return {}


def save(work: str, name: str, shots: dict):
    projectstore.write_json(path(work, name), {"shots": shots})


def clean_query(visual: str) -> str:
    """The shot idea without the editing words ('Cut to', 'B-Roll of'): what is left is what should be on screen."""
    words = [w for w in re.split(r"\W+", visual) if w and w.lower() not in FILLER]
    return " ".join(words) or visual


TO_CAMERA = re.compile(r"\b(speaking|talking|looking|facing|smiling)\b[^.]{0,30}\bcamera\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def programs(rels) -> set:
    """Names of the programs / subjects the host filed his footage under: the first folder of each clip (Blender/, Fusion/, TinkerCad/ ...), lower case."""
    out = set()
    for rel in rels:
        parts = str(rel).replace("\\", "/").split("/")
        if len(parts) > 1 and len(_norm(parts[0])) >= 4:
            out.add(_norm(parts[0]))
    return out


def named_programs(visual: str, known: set) -> set:
    """The known programs a shot idea names ('Placing Onshape and Autodesk Fusion in A-Tier' -> onshape, fusion)."""
    words = [w for w in re.split(r"\W+", clean_query(visual)) if w]          # without the editing words: "B-Roll" must not mean a folder called B Roll
    toks = {_norm(w) for w in words} | {_norm(a + b) for a, b in zip(words, words[1:])}          # also 'Free CAD' / 'Open SCAD'
    out = known & toks
    for k in known - out:                                    # the transcript spells names as they sound: "Shaper 3D" for Shapr3D
        if len(k) >= 6 and any(len(t) >= 6 and difflib.SequenceMatcher(None, k, t).ratio() >= 0.85 for t in toks):
            out.add(k)
    return out


def of_program(rel: str, names: set, label: str = "") -> bool:
    """The clip's folder or file name names one of the programs, or the user's tag on this moment of it does (`label`)."""
    n = _norm(rel) + _norm(label)
    return any(k in n for k in names)


def label_at(tag_list: list, rel: str, t: float) -> str:
    import tags
    tg = tags.at(tag_list or [], rel, float(t))
    return tg["label"] if tg else ""


def plan(work: str, name: str) -> list:
    """Every shot idea of the outline in order: [{key, visual, section, camera, speech (the spoken line it goes with, internal id), kind}]."""
    model = outline.load(work, name)
    out = []
    for ln in outline.speech_lines(model):
        for v in ln["visuals"] + ln.get("after", []):
            out.append({"key": outline.shot_key(ln["heading"], v), "visual": v, "section": ln["heading"], "camera": outline.is_camera(v),
                        "speech": ln["id"], "kind": ln["kind"]})
    return out


def _entry(old: dict | None, shot: dict) -> dict:
    return old if old and old.get("visual") == shot["visual"] else {"visual": shot["visual"], "section": shot["section"], "chosen": None, "candidates": [], "by": "auto"}


def match(work: str, name: str) -> dict:
    """Look every non-camera shot idea up in the vision library. Choices made by Claude or the host are kept. Returns {ready, nothing, total}."""
    saved = load(work, name)
    shots, ready, nothing = {}, 0, 0
    jp = brolllib.paths(work, name)[1]
    known = programs(json.loads(jp.read_text(encoding="utf-8")).get("clips", {})) if jp.exists() else set()
    for s in plan(work, name):
        if s["camera"]:
            continue
        e = _entry(saved.get(s["key"]), s)
        if e["by"] == "auto":
            named = named_programs(s["visual"], known)
            hits = brolllib.search(work, clean_query(s["visual"]), top=60, name=name)
            hits = [h for h in hits if not TO_CAMERA.search(h.get("what") or "")]         # The creator talking to the camera is a talking take, not a cutaway
            tier = [h for h in hits if "tierlist" in _norm(h["rel"])] if re.search(r"tier", s["visual"], re.I) else []
            if tier:                                   # a shot about a tier list: the tier-list recording (icons going onto the list), whatever program it names
                named = set()
                hits = tier
            if named:                                  # the shot is about a program: footage of another program cannot be the answer
                hits = [h for h in hits if of_program(h["rel"], named, h["what"] if h.get("tagged") else "")]
            hits = hits[:TOP]
            e["candidates"] = [{k: h[k] for k in ("rel", "t", "score", "what", "dur")} for h in hits]
            e["chosen"] = e["candidates"][0] if tier and e["candidates"] else next((c for c in e["candidates"] if c["score"] >= THRESH), None)
        shots[s["key"]] = e
        if e["chosen"]:
            ready += 1
        else:
            nothing += 1
    save(work, name, shots)
    return {"ready": ready, "nothing": nothing, "total": ready + nothing}


def ambiguous(work: str, name: str) -> list:
    """Shots with two or more likely clips that nobody has chosen between yet: the only ones Claude is asked about."""
    return [(k, e) for k, e in load(work, name).items() if e["by"] == "auto" and sum(1 for c in e["candidates"] if c["score"] >= THRESH) >= 2]


def pick_brief(work: str, name: str, fd: Path) -> str:
    fd.mkdir(parents=True, exist_ok=True)
    rows = [{"key": k, "shot_idea": e["visual"], "clips": [{"number": i, "what_it_shows": c["what"], "score": c["score"]}
                                                           for i, c in enumerate(e["candidates"]) if c["score"] >= THRESH]} for k, e in ambiguous(work, name)]
    (fd / "shots.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    got = skillrules.copy_into(fd, ("youtube-edit/rough-cut.md", "youtube-edit/editing-style.md", "youtube-edit/lessons.md"))
    return (skillrules.read_first_line(got) + "shots.json lists shot ideas from the host's outline and, for each, the clips of his footage that might fit (what each clip shows, from a vision model). "
            "For each shot idea pick the clip that best shows what the idea asks for, or none if no clip really fits. Write picks.json here:\n"
            '{"picks": [{"key": "<key from shots.json>", "clip": <the clip number, or null for none>, "why": "<one plain sentence>"}]}\n'
            "Descriptions can be wrong in small details; judge by the whole description. Write nowhere else.")


def apply_picks(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        picks = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("picks", [])
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    shots = load(work, name)
    n = 0
    for pk in picks:
        e = shots.get(pk.get("key")) if isinstance(pk, dict) else None
        if not e or e["by"] != "auto":
            continue
        i = pk.get("clip")
        if i is None:
            e["chosen"], e["by"] = None, "claude"
        elif isinstance(i, int) and 0 <= i < len(e["candidates"]):
            e["chosen"], e["by"] = e["candidates"][i], "claude"
        else:
            continue
        n += 1
    save(work, name, shots)
    return True, f"Claude chose between clips for {n} shot{'s' if n != 1 else ''}."


def choose(work: str, name: str, key: str, index: int | None) -> dict:
    """The host picks one of the clips offered for a shot, or none."""
    shots = load(work, name)
    e = shots.get(key)
    if not e:
        raise ValueError("that shot is not in the outline any more")
    if index is None:
        e["chosen"] = None
    elif 0 <= index < len(e["candidates"]):
        e["chosen"] = e["candidates"][index]
    else:
        raise ValueError("that clip is not one of the choices")
    e["by"] = "user"
    save(work, name, shots)
    return e


def apply_to_beats(work: str, name: str) -> int:
    """Under each spoken line that has a chosen clip, put it in the beat map as a cutaway covering the line. Cutaways placed by hand stay."""
    import beatmap
    bp = WORK / work / f"{name}.beatmap.json"
    try:
        data = json.loads(bp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return 0
    shots = load(work, name)
    by_line = {}
    for s in plan(work, name):
        e = shots.get(s["key"])
        if e and e["chosen"] and s["speech"] not in by_line:
            by_line[s["speech"]] = e["chosen"]
    n = 0
    for b in data["beats"]:
        if b.get("vo") or b.get("skip") or not b.get("aroll"):
            continue
        hit = next((by_line[ln] for ln in b.get("script_lines", []) if ln in by_line), None)
        broll = b.setdefault("on_screen", {}).setdefault("broll", [])
        if any(not x.get("auto") for x in broll):                       # somebody placed a cutaway here
            continue
        broll[:] = []
        if hit:
            room = max(1.0, float(hit.get("dur") or b["dur"]) - float(hit["t"]))
            broll.append({"file": hit["rel"], "in": float(hit["t"]), "dur": round(min(float(b["dur"]), room), 2), "at": 0.0, "why": hit["what"][:120], "auto": True})
            n += 1
    beatmap.write_json(bp, data)
    return n


def rows(work: str, name: str) -> list:
    """For the Footage screen, per section: what is there for each shot idea and each spoken line. [{section, items: [...]}]."""
    import views
    shots = load(work, name)
    try:
        clips = json.loads((WORK / work / f"{name}.clips.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        clips = {}
    by_line = clips.get("by_line", {})
    spans = {sp["id"]: sp for c in clips.get("clips", []) for sp in c["spans"]}
    out, sec = [], None
    model = outline.load(work, name)
    for ln in outline.speech_lines(model):
        if sec is None or sec["section"] != ln["heading"]:
            sec = {"section": ln["heading"], "items": []}
            out.append(sec)
        for v in ln["visuals"] + ln.get("after", []):
            key = outline.shot_key(ln["heading"], v)
            if outline.is_camera(v):
                continue
            e = shots.get(key)
            sec["items"].append({"type": "shot", "key": key, "text": v, "status": "ready" if e and e["chosen"] else "nothing",
                                 "by": e["by"] if e else "auto", "candidates": (e["candidates"] if e else [])[:TOP], "chosen": e["chosen"] if e else None})
        sid = (by_line.get(ln["id"]) or {}).get("picked")
        sp = spans.get(sid) if sid else None
        sec["items"].append({"type": "take", "text": views._summary(ln["said"], 70), "status": "ready" if sp else "nothing",
                             "len": views.time_text(sp["dur"]) if sp else ""})
    return out


def missing(work: str, name: str) -> list:
    """The list the host can copy: shots and lines that still have nothing, in plain words."""
    out = []
    for sec in rows(work, name):
        for it in sec["items"]:
            if it["status"] == "nothing":
                out.append(f"{sec['section']}: " + (f"film or find: {it['text']}" if it["type"] == "shot" else f"say it to camera: {it['text']}"))
    return out
