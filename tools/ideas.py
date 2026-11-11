"""B-roll and on-screen text ideas for the rough cut screen: Claude suggests, the host says yes or no to each one.

`<name>.ideas.json` (a plan file): {"ideas": [{"id": "i3", "beat": "B07", "at": 2.4, "kind": KIND, "text": "...", "why": "...", "status": "suggested|yes|no",
                                              "rel": ..., "t": ... (footage), "url": ..., "find": ... (web), "pickup": "P02" (film, once added)}]}
Kinds:
  footage     a moment of the host's own footage (rel, t) over the clip                -> a B-roll insert in the beat map
  web         a public page (url, find) captured over the clip                         -> a 'web' clip choice (the server captures it)
  film        nothing fits: a shot to film next time                                   -> a pickup on the shoot plan
  correction  the host misspoke: the right words on screen ("*0.4 mm, not 0.6")       -> on_screen.text of the beat (textcards.py)
  detail      a short fact on screen (a price, a model number, a setting)              -> on_screen.text of the beat
`at` is seconds into the beat's clip as it plays in the cut. A yes on footage or text becomes a clip choice (reviewnotes, kind "idea"); like Replace and Trim it is
applied, and listed under What changed, when the next cut is made (apply_choice). Taking a yes back before then removes the choice; after it, a choice that
takes the insert out again. The rules for Claude are the youtube-edit skill's ideas.md; the numbers are rough-cut.json's `ideas_max`, `text_card_s`, `broll_max_s`.
"""
import json
import re
from pathlib import Path

import beatmap
import config
import projectstore
import reviewnotes
import skillrules
import textcards

WORK = config.WORK
KINDS = ("footage", "web", "film", "correction", "detail")
TEXT_KINDS = ("correction", "detail")
STAGE = "cut"
SHOT_S = 4.0                    # how long a cutaway from the host's footage shows (at most broll_max_s)


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.ideas.json"


def load(work: str, name: str) -> list:
    try:
        return json.loads(path(work, name).read_text(encoding="utf-8-sig")).get("ideas", [])
    except (OSError, ValueError, AttributeError):
        return []


def save(work: str, name: str, ideas: list):
    projectstore.write_json(path(work, name), {"ideas": ideas})


def _bm(work: str, name: str) -> dict:
    try:
        return json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"beats": []}


def _clock(t: float) -> str:
    t = int(round(t or 0))
    return f"{t // 60}:{t % 60:02d}"


def _library(work: str, name: str) -> dict:
    """{rel: {dur, samples}} of the footage library (brolllib.py); empty when the footage has not been looked at."""
    import brolllib
    _, jp, _, _ = brolllib.paths(work, name)
    try:
        return json.loads(jp.read_text(encoding="utf-8")).get("clips", {})
    except (OSError, ValueError):
        return {}


def _alike(a: str, b: str) -> bool:
    """Two subjects that share most of their words ('3d printer print bed' / '3d printer')."""
    x, y = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= 0.6


def footage_lines(lib: dict, skip_rels: set) -> list:
    """The footage as Claude reads it (footage.txt): one line per run of samples that show much the same thing,
    '<rel> | 12-48 s | the first description | also: other subject @ 30 s, ...'. The recordings the cut uses as takes are left out (the host talking)."""
    out = []
    for rel, c in sorted(lib.items()):
        if rel in skip_rels:
            continue
        run = None
        for s in sorted(c.get("samples") or [], key=lambda x: x.get("t", 0)):
            subj = str(s.get("subject") or "").strip().lower()
            if run and any(_alike(x, subj) for x in run["subjects"]):         # the model words the same thing a little differently frame to frame
                run["end"] = s["t"]
                if subj not in run["subjects"] and len(run["also"]) < 4:
                    run["subjects"].append(subj)
                    run["also"].append(f"{subj} @ {s['t']:g} s")
                continue
            if run:
                out.append(run)
            run = {"rel": rel, "start": s["t"], "end": s["t"], "subjects": [subj], "also": [], "what": " ".join(str(s.get("what") or "").split())[:100]}
        if run:
            out.append(run)
    return [f"{r['rel']} | {r['start']:g}-{r['end']:g} s | {r['what']}" + (f" | also: {', '.join(r['also'])}" if r["also"] else "") for r in out]


def has_broll(b: dict) -> bool:
    """A cutaway over the clip already (a voice-over's first picture IS the clip, so it does not count)."""
    inserts = [x for x in (b.get("on_screen") or {}).get("broll", []) if x.get("file")]
    return len(inserts) > (1 if b.get("vo") else 0)


def find_prompt(work: str, name: str, fd: Path) -> str:
    fd.mkdir(parents=True, exist_ok=True)
    bm = _bm(work, name)
    import locks
    good = locks.beat_ids(work, name, bm)
    rows = [{"beat": b["id"], "starts_at": _clock(float(b.get("start") or 0)), "seconds": round(float(b.get("dur") or 0), 1), "said": b.get("said", ""),
             "has_broll": has_broll(b), "has_graphic": bool(b.get("graphic")), "has_text": bool((b.get("on_screen") or {}).get("text")), "good": b["id"] in good}
            for b in bm.get("beats", []) if b.get("said") and not b.get("skip")]
    (fd / "beats.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    takes = {(b.get("aroll") or {}).get("rel") for b in bm.get("beats", [])}
    lines = footage_lines(_library(work, name), takes)
    (fd / "footage.txt").write_text("\n".join(lines) or "(the footage has not been looked at yet: suggest web pages and shots to film instead)", encoding="utf-8")
    import accuracy
    fc = accuracy.read(work, name)
    gone = set(fc.get("dismissed") or [])
    wrong = [{k: c.get(k) for k in ("beat", "quote", "claim", "verdict", "explanation", "suggestion")} for c in fc.get("claims") or []
             if c.get("verdict") in ("incorrect", "misleading", "imprecise") and c.get("id") not in gone]
    (fd / "factcheck.json").write_text(json.dumps(wrong, indent=1, ensure_ascii=False), encoding="utf-8")
    script = WORK / work / f"{name}.script.md"
    if script.is_file():
        (fd / "script.md").write_text(script.read_text(encoding="utf-8-sig"), encoding="utf-8")
    got = skillrules.copy_into(fd, "ideas")
    r = skillrules.rules()
    taken = [f"{i['beat']} {i['kind']}: {i['text']}" for i in load(work, name) if i["status"] in ("yes", "no")]
    (fd / "decided.txt").write_text("\n".join(taken) or "(none)", encoding="utf-8")
    return ("beats.json is what the host says in each clip of the host's rough cut, in order (has_broll / has_graphic / has_text: the clip already has one; good: the host marked it good). "
            "footage.txt lists the host's own footage by what it shows (recording | seconds | subject: what). factcheck.json lists claims the fact check found wrong; "
            "script.md, when it is there, is what the host planned to say. " + skillrules.read_first_line(got) + "ideas.md holds the rules for this job.\n"
            f"Suggest B-roll and on-screen text for this cut: at most {r['ideas_max']} ideas in all, the best first. A B-roll idea shows at most {r['broll_max_s']:g} seconds; "
            f"a text card shows about {r['text_card_s']:g} seconds. decided.txt lists ideas the host already said yes or no to: do not suggest them again.\n"
            "Write ideas.json here:\n"
            '{"ideas": [{"beat": "<beat id>", "quote": "<the first few words the host says where it should start, copied from said>", '
            '"kind": "footage|web|film|correction|detail", "text": "<footage/film: what the picture shows, in a few words; correction/detail: the exact words on screen>", '
            '"rel": "<footage: the recording from footage.txt>", "t": <footage: the second in that recording>, '
            '"url": "<web: the public address>", "find": "<web: a few words that are on the page, or empty>", "why": "<one plain sentence>"}]}\n'
            "Write nowhere else.")


def _check(f: dict, b: dict, lib: dict):
    """The idea's own fields, cleaned, or None when it cannot be used."""
    kind = f.get("kind")
    text = " ".join(str(f.get("text") or "").split())
    if kind in TEXT_KINDS:
        text = textcards.clean(text)
        return {"text": text} if text else None
    if kind == "footage":
        c = lib.get(str(f.get("rel") or ""))
        try:
            t = float(f.get("t"))
        except (TypeError, ValueError):
            return None
        if not c or not 0 <= t <= float(c.get("dur") or 0):
            return None
        return {"text": text[:120] or "a shot from your footage", "rel": f["rel"], "t": round(t, 2)}
    if kind == "web":
        import webcapture
        try:
            url = webcapture.check_url(str(f.get("url") or ""))
        except ValueError:
            return None
        return {"text": text[:120] or url, "url": url, "find": " ".join(str(f.get("find") or "").split())[:200]}
    if kind == "film":
        return {"text": text[:200]} if len(text) >= 3 else None
    return None


def import_found(work: str, name: str, p: Path) -> tuple[bool, str]:
    """Claude's ideas replace the ideas still waiting for an answer; the ones the host answered stay."""
    try:
        found = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("ideas", [])
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    import accuracy
    by = {b["id"]: b for b in _bm(work, name).get("beats", []) if not b.get("skip")}
    lib = _library(work, name)
    ideas = [i for i in load(work, name) if i["status"] != "suggested"]
    seen = {(i["beat"], i["kind"], i["text"].lower()) for i in ideas}
    n_id = 1 + max([int(re.sub(r"\D", "", i["id"]) or 0) for i in load(work, name)] + [0])
    room = skillrules.rules()["ideas_max"]
    n = 0
    for f in found if isinstance(found, list) else []:
        if n >= room or not isinstance(f, dict) or f.get("kind") not in KINDS:
            continue
        b = by.get(f.get("beat"))
        own = _check(f, b, lib) if b else None
        if not own or (b["id"], f["kind"], own["text"].lower()) in seen:
            continue
        at = min(accuracy.quote_at(b, str(f.get("quote") or "")), max(0.0, float(b.get("dur") or 0) - 1.0))
        ideas.append({"id": f"i{n_id}", "beat": b["id"], "at": round(at, 2), "kind": f["kind"], **own, "why": " ".join(str(f.get("why") or "").split())[:200],
                      "status": "suggested"})
        seen.add((b["id"], f["kind"], own["text"].lower()))
        n_id += 1
        n += 1
    save(work, name, ideas)
    return n > 0, f"Claude has {n} idea{'s' if n != 1 else ''} for B-roll and on-screen text." if n else "Claude found nothing to add."


def add_own(work: str, name: str, t: float, text: str, kind: str = "correction") -> dict:
    """The host's own on-screen text at a moment of the cut (a yes straight away). Returns the idea."""
    import noteactions
    if kind not in TEXT_KINDS:
        raise ValueError("unknown kind of text")
    text = textcards.clean(text)
    if not text:
        raise ValueError("type the text to show")
    beats = _bm(work, name).get("beats", [])
    b, at = noteactions.beat_at(beats, float(t))
    ideas = load(work, name)
    n_id = 1 + max([int(re.sub(r"\D", "", i["id"]) or 0) for i in ideas] + [0])
    idea = {"id": f"i{n_id}", "beat": b["id"], "at": round(min(at, max(0.0, float(b.get("dur") or 0) - 1.0)), 2), "kind": kind, "text": text,
            "why": "Added by you", "status": "suggested", "own": True}
    ideas.append(idea)
    save(work, name, ideas)
    set_status(work, name, idea["id"], "yes")
    return idea


def _choice_text(i: dict, start: float) -> str:
    when = _clock(start + float(i.get("at") or 0))
    if i["kind"] in TEXT_KINDS:
        return f"Show “{i['text']}” at {when}"
    return f"Show {i['text']} at {when}"


def _drop_choice(j: dict, iid: str):
    j[STAGE] = [n for n in j[STAGE] if not (n.get("kind") == "idea" and (n.get("choice") or {}).get("idea") == iid and n.get("status") != "done")]


def _add_choice(j: dict, i: dict, start: float, remove: bool = False):
    nid = 1 + max([n["id"] for n in j[STAGE]] + [0])
    text = ("Take out: " if remove else "") + _choice_text(i, start)
    j[STAGE].append({"id": nid, "t": round(start + float(i.get("at") or 0), 1), "t_end": None, "text": text, "clip": i["beat"], "kind": "idea",
                     "choice": {"idea": i["id"], **({"remove": True} if remove else {})}, "status": "open", "applied_in": None})


def in_plan(b: dict, iid: str) -> bool:
    on = b.get("on_screen") or {}
    return any(x.get("idea") == iid for x in (on.get("broll") or []) + (on.get("text") or []))


def set_status(work: str, name: str, iid: str, status: str, text: str | None = None) -> dict:
    """yes / no / suggested for one idea. Footage and text become clip choices (applied by the next cut); film adds or removes a pickup.
    A web page is captured by the server (it needs a background job); here it only records the answer. Returns the idea."""
    if status not in ("yes", "no", "suggested"):
        raise ValueError("unknown answer")
    ideas = load(work, name)
    i = next((x for x in ideas if x["id"] == iid), None)
    if not i:
        raise ValueError("there is no such idea")
    if text is not None and i["kind"] in TEXT_KINDS and status == "yes":
        t = textcards.clean(text)
        if not t:
            raise ValueError("type the text to show")
        i["text"] = t
    b = next((x for x in _bm(work, name).get("beats", []) if x["id"] == i["beat"]), None)
    if b is None:
        raise ValueError("that clip is no longer in the cut")
    if i["kind"] in ("footage", *TEXT_KINDS):
        with reviewnotes._lock:
            j = reviewnotes.load(work, name)
            _drop_choice(j, iid)
            there = in_plan(b, iid)
            if status == "yes" and not there:
                _add_choice(j, i, float(b.get("start") or 0))
            elif status != "yes" and there:
                _add_choice(j, i, float(b.get("start") or 0), remove=True)
            reviewnotes.save(work, name, j)
    elif i["kind"] == "film":
        import shootplan
        if status == "yes" and not i.get("pickup"):
            st = shootplan.apply_op(work, name, "pickup_add", {"what": i["text"], "lines": list(b.get("script_lines") or [])})
            i["pickup"] = st["pickups"][-1]["id"] if st.get("pickups") else ""
        elif status != "yes" and i.get("pickup"):
            shootplan.apply_op(work, name, "pickup_del", {"id": i["pickup"]})
            i.pop("pickup", None)
    i["status"] = status
    save(work, name, ideas)
    return i


def insert_for(b: dict, i: dict, lib_dur: float | None, rules: dict) -> dict:
    """The B-roll insert of a footage idea, kept inside the beat and inside its recording."""
    beat_dur = float(b.get("dur") or 0)
    dur = min(SHOT_S, float(rules["broll_max_s"]), max(1.0, beat_dur - 0.2))
    at = min(max(0.0, float(i.get("at") or 0)), max(0.0, beat_dur - dur))
    src = max(0.0, float(i["t"]) - 1.0)
    if lib_dur:
        src = min(src, max(0.0, float(lib_dur) - dur))
    return {"file": i["rel"], "in": round(src, 2), "dur": round(dur, 2), "at": round(at, 2), "why": f"Idea: {i['text']}"[:160], "idea": i["id"]}


def apply_choice(work: str, name: str, b: dict, ch: dict) -> str | None:
    """One 'idea' clip choice on beat b (cutview.apply_choices). Returns the sentence for What changed, or None when there is nothing to do."""
    i = next((x for x in load(work, name) if x["id"] == ch.get("idea")), None)
    if not i:
        return None
    on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
    when = _clock(float(b.get("start") or 0) + float(i.get("at") or 0))
    if ch.get("remove"):
        on["broll"] = [x for x in on.get("broll", []) if x.get("idea") != i["id"]]
        on["text"] = [x for x in on.get("text") or [] if x.get("idea") != i["id"]]
        if not on["text"]:
            on.pop("text")
        return f"Took out the idea at {when} ({i['text'][:60]})"
    if i["kind"] == "footage":
        lib = _library(work, name)
        on["broll"] = [x for x in on.get("broll", []) if x.get("idea") != i["id"]] + [insert_for(b, i, (lib.get(i["rel"]) or {}).get("dur"), skillrules.rules())]
        return f"Put the shot of {i['text'][:80]} over the clip at {when}"
    if i["kind"] in TEXT_KINDS:
        e = textcards.entry({"text": i["text"], "kind": i["kind"], "at": i.get("at", 0)}, float(b.get("dur") or 0), skillrules.rules()["text_card_s"])
        on["text"] = [x for x in on.get("text") or [] if x.get("idea") != i["id"]] + [{**e, "idea": i["id"]}]
        return f"Showed “{e['text']}” on screen at {when}"
    return None
