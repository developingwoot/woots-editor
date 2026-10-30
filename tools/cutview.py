"""The rough cut for the v2 review screen (ADR 0007): the clips of the cut, other takes to swap in, the host's choices, and the render.

A clip of the cut is one beat of the beat map that has picture (an A-roll take, or a voice-over's B-roll). The host's choices are notes in the
review notes store (reviewnotes), one open choice per clip: kind 'replace' {span}, 'remove', 'trim' {in, out}. `apply_choices` turns them into
beat map edits by code (written through beatmap.write_json, so they are recorded and undoable). Free-text notes are for Claude (makeversion).
The rough cut render is the whole beat map with graphics, sound effects and music left out: clips only, half size, no tokens.
"""
import json
import time
from pathlib import Path

import beatmap
import clipmap
import config
import reviewnotes

WORK = config.WORK
STAGE = "cut"
TRIM_MIN = 1.0          # a trimmed clip keeps at least this many seconds


def _read(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def beat_data(work: str, name: str) -> dict:
    d = _read(WORK / work / f"{name}.beatmap.json")
    if not d:
        raise ValueError("there is no plan to cut from yet")
    return d


def has_picture(b: dict) -> bool:
    if b.get("skip"):
        return False
    return bool(b.get("aroll")) or bool(b.get("vo") and any(x.get("file") for x in (b.get("on_screen") or {}).get("broll", [])))


def clip_beats(data: dict) -> list:
    return [b for b in data["beats"] if has_picture(b)]


def clips_of(data: dict) -> list:
    """The clips of the cut in order: [{ref (the beat id, internal), start, dur, said}], times as the beat map estimates them."""
    return [{"ref": b["id"], "start": b.get("start", 0.0), "dur": b.get("dur", 0.0), "said": b.get("said", "")} for b in clip_beats(data)]


def _line_candidates(work: str, name: str, b: dict) -> list:
    """Other takes that read this beat's script line, best first: [(span, rel)]. Skipped spans and the one in use are left out."""
    clips = _read(WORK / work / f"{name}.clips.json")
    if not clips or not b.get("aroll") or not b.get("script_lines"):
        return []
    spans = {sp["id"]: (sp, c["rel"]) for c in clips["clips"] for sp in c["spans"]}
    cands = (clips.get("by_line", {}).get(b["script_lines"][0]) or {}).get("candidates") or []
    return [spans[i] for i in cands if i in spans and i != b["aroll"].get("span") and not spans[i][0].get("skip")]


def _why(sp: dict, line: str) -> str:
    cov = int(sp.get("coverage", {}).get(line, 0) * 100)
    rest = sp.get("restarts") or 0
    return f"Reads {cov}% of the line, " + ("no restarts" if not rest else f"{rest} restart{'s' if rest != 1 else ''}")


def options(work: str, name: str, ref: str, limit: int = 3) -> list:
    """Up to `limit` other pictures or takes for the clip: [{span, rel, start, dur, said, why}]. `span` is internal (the page sends it back).
    A clip with a take of the host speaking gets his other takes of that line; a clip that is only a picture (B-roll under a voice-over) gets
    the moments of the footage that LOOK like it, found with the vision library (no speech needed)."""
    b = next((x for x in beat_data(work, name)["beats"] if x["id"] == ref), None)
    if not b:
        raise ValueError("unknown clip")
    if not b.get("aroll"):
        return _picture_options(work, name, b, limit)
    line = b["script_lines"][0] if b.get("script_lines") else ""
    return [{"span": sp["id"], "rel": rel, "start": sp["start"], "dur": sp["dur"], "said": (sp.get("text") or "")[:160], "why": _why(sp, line)}
            for sp, rel in _line_candidates(work, name, b)[:limit]]


def _current_pictures(work: str, name: str, b: dict) -> list:
    import shootplan
    folder, _ = shootplan.footage_folder(work, name)
    out = []
    for x in (b.get("on_screen") or {}).get("broll", []):
        f = x.get("file")
        if f:
            p = Path(f)
            try:
                out.append(p.relative_to(folder).as_posix() if p.is_absolute() and folder else p.as_posix())
            except ValueError:
                out.append(p.as_posix())
    return out


def _picture_options(work: str, name: str, b: dict, limit: int) -> list:
    import brolllib
    brs = [x for x in (b.get("on_screen") or {}).get("broll", []) if x.get("file")]
    if not brs:
        return []
    query = " ".join(x for x in [(b.get("vo") or {}).get("term"), brs[0].get("why"), b.get("said")] if x)
    hits = brolllib.search(work, query, top=limit, name=name, exclude=tuple(_current_pictures(work, name, b)))
    dur = float(brs[0].get("dur") or b.get("dur") or 2)
    return [{"span": f"v|{h['rel']}|{h['t']}", "rel": h["rel"], "start": h["t"], "dur": dur, "said": h["what"],
             "why": f"Looks like: {h['subject'] or h['what']}"[:120]} for h in hits]


def has_take(work: str, name: str, ref: str) -> bool:
    """True when the clip is a take of the host speaking (not only a picture)."""
    b = next((x for x in beat_data(work, name)["beats"] if x["id"] == ref), None)
    return bool(b and b.get("aroll"))


def vision_status(work: str, name: str) -> dict:
    """{ready, described, total}: has the vision library looked at all the footage? (Picture options need it.)"""
    import brolllib
    st = brolllib.state(work, name)
    return {"ready": st["ready"], "described": st["described"], "total": st["total"], "missing": len(st["missing"])}


def set_choice(work: str, name: str, ref: str, kind: str, text: str, t: float, choice: dict | None = None) -> None:
    """The host picks Keep / Replace / Remove / Trim for a clip. Keep clears the clip's open choice; the others replace it (one choice per clip)."""
    if kind not in ("keep", "replace", "remove", "trim"):
        raise ValueError("unknown choice")
    with reviewnotes._lock:
        j = reviewnotes.load(work, name)
        j[STAGE] = [n for n in j[STAGE] if not (n.get("clip") == ref and n.get("choice") is not None and n.get("status") != "done")]
        if kind != "keep":
            nid = 1 + max([n["id"] for n in j[STAGE]] + [0])
            j[STAGE].append({"id": nid, "t": round(float(t), 1), "t_end": None, "text": text, "clip": ref, "kind": kind, "choice": choice or {},
                             "status": "open", "applied_in": None})
        reviewnotes.save(work, name, j)


def _replace_take(b: dict, sp: dict, rel: str):
    b["aroll"] = {"rel": rel, "in": sp["start"], "out": sp["end"], "dur": sp["dur"], "span": sp["id"], "span_in": sp["start"], "span_out": sp["end"],
                  "keep": None, "words": []}
    b["said"], b["dur"], b["flags"] = sp.get("text", ""), sp["dur"], list(sp.get("flags", []))


def apply_choices(work: str, name: str) -> dict:
    """The open exact choices become beat map edits. Returns {applied_ids, changes}: one plain sentence per choice."""
    data = beat_data(work, name)
    clips = _read(WORK / work / f"{name}.clips.json") or {}
    spans = {sp["id"]: (sp, c["rel"]) for c in clips.get("clips", []) for sp in c["spans"]}
    by_id = {b["id"]: b for b in data["beats"]}
    ids, changes, picked = [], [], {}
    for n in reviewnotes.open_notes(work, name, STAGE):
        b, ch = by_id.get(n.get("clip")), n.get("choice")
        if not b or ch is None:
            continue
        at = _clock(n["t"])
        if n["kind"] == "remove":
            b["skip"] = True
            changes.append(f"Took out the clip at {at}")
        elif n["kind"] == "replace" and str(ch.get("span", "")).startswith("v|") and (b.get("on_screen") or {}).get("broll"):
            _, rel, t = ch["span"].split("|", 2)                 # another picture: the first B-roll insert shows a different moment of the footage
            first = b["on_screen"]["broll"][0]
            first["file"], first["in"] = rel, float(t)
            changes.append(f"Swapped the picture at {at} for another shot")
        elif n["kind"] == "replace" and ch.get("span") in spans and b.get("aroll"):
            sp, rel = spans[ch["span"]]
            _replace_take(b, sp, rel)
            for ln in b.get("script_lines", []):
                picked[ln] = sp["id"]
            changes.append(f"Swapped the clip at {at} for another take")
        elif n["kind"] == "trim" and b.get("aroll"):
            a = b["aroll"]
            lo, hi = float(a["span_in"]), float(a["span_out"])
            want_in = a["in"] + float(ch["cut_start"]) if "cut_start" in ch else float(ch.get("in", a["in"]))
            want_out = a["out"] - float(ch["cut_end"]) if "cut_end" in ch else float(ch.get("out", a["out"]))
            new_in = min(max(want_in, lo), hi - TRIM_MIN)
            new_out = max(min(want_out, hi), new_in + TRIM_MIN)
            a["in"], a["out"], a["dur"], a["keep"] = round(new_in, 2), round(new_out, 2), round(new_out - new_in, 2), None
            b["dur"] = a["dur"]
            changes.append(f"Trimmed the clip at {at}")
        else:
            continue
        ids.append(n["id"])
        data["changes"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "user", "beat": b["id"], "what": changes[-1]})
    if not ids:
        return {"applied_ids": [], "changes": []}
    beatmap.retime(data["beats"])
    beatmap.write_json(WORK / work / f"{name}.beatmap.json", data)
    if picked and clips.get("by_line"):                 # the beat map's own 'update from clips' keeps the creator's pick
        for ln, sid in picked.items():
            clips["by_line"].setdefault(ln, {}).update({"picked": sid, "picked_by": "user"})
        clipmap.write_json(WORK / work / f"{name}.clips.json", clips)
    return {"applied_ids": ids, "changes": changes}


def _clock(t: float) -> str:
    import views
    return views.time_text(t)


# ----------------------------------------------------------------------------- the render
def edit_for(data: dict, folder: str) -> dict:
    """The section.edit.json of the whole video with clips only: no graphics, no sound effects (music is never part of a section render)."""
    import sections
    edit = sections.baseline_edit(data["beats"], folder, built={})
    edit["overlays"], edit["sfx"] = [], []
    return edit


def free_output(p: Path):
    """Earlier cuts are kept as hard links to this file (reviewnotes), and the renderer writes in place: unlink first so a new render never rewrites an old version."""
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def render(work: str, name: str) -> tuple[Path, list]:
    """Render the rough cut. Returns (video path, clips [{start, dur, ref}] as rendered). Raises ValueError with a plain sentence."""
    import sectionrender
    import shootplan
    data = beat_data(work, name)
    folder, _ = shootplan.footage_folder(work, name)
    if not folder:
        raise ValueError("the footage folder is not set")
    edit = edit_for(data, str(folder))
    import loudness
    loudness.set_gains(work, name, edit, str(folder))
    if not edit["segments"]:
        raise ValueError("there are no clips to cut yet")
    d = WORK / work / "v2-cut"
    d.mkdir(exist_ok=True)
    edit_path = d / "cut.edit.json"
    edit_path.write_text(json.dumps(edit, indent=1), encoding="utf-8")
    free_output(d / "out" / "cut.mp4")
    try:
        info = sectionrender.render(edit_path, d / "out", "cut.mp4")
    except (ValueError, RuntimeError) as e:
        raise ValueError(f"the cut could not be made: {e}") from e
    rows = []
    for s in info["segments"]:
        ref = str(s["id"]).split(".")[0]
        if rows and rows[-1]["ref"] == ref:                 # the pieces of a trimmed beat are one clip
            rows[-1]["dur"] = round(s["out_start"] + s["out_dur"] - rows[-1]["start"], 2)
        else:
            rows.append({"ref": ref, "start": s["out_start"], "dur": s["out_dur"]})
    return d / "out" / "cut.mp4", rows


# ----------------------------------------------------------------------------- find more takes (searches all the footage)
GAP = 1.2           # s of silence that ends a chunk of speech
CHUNK_WORDS = 45


def transcript_chunks(work: str, name: str) -> list:
    """Everything said in every recording, in chunks Claude can read: [{rel, start, end, text}]."""
    cfg = _read(WORK / work / f"{name}.footage.json", {}) or {}
    out = []
    for rel, an in (cfg.get("analysis") or {}).items():
        cur = []
        for w in (an or {}).get("list") or []:
            if cur and (w[1] - cur[-1][2] > GAP or len(cur) >= CHUNK_WORDS):
                out.append(_chunk(rel, cur))
                cur = []
            cur.append(w)
        if cur:
            out.append(_chunk(rel, cur))
    return out


def _chunk(rel: str, words: list) -> dict:
    return {"rel": rel, "start": round(words[0][1], 2), "end": round(words[-1][2], 2), "text": " ".join(w[0] for w in words)}


def search_prompt(work: str, name: str, ref: str, fd: Path) -> str:
    b = next((x for x in beat_data(work, name)["beats"] if x["id"] == ref), None)
    if not b or not b.get("aroll"):
        raise ValueError("unknown clip")
    fd.mkdir(parents=True, exist_ok=True)
    (fd / "transcripts.json").write_text(json.dumps(transcript_chunks(work, name), indent=0), encoding="utf-8")
    (fd / "wanted.json").write_text(json.dumps({"said": b.get("said", ""), "in_use": {"rel": b["aroll"]["rel"], "start": b["aroll"]["in"]}}), encoding="utf-8")
    return ("wanted.json is what the host says in one clip of his video. transcripts.json is everything said in all his recordings "
            "(each chunk has the recording, start and end in seconds, and the words). Find up to 3 other places where he says the same thing, "
            "not the one in use. A good take reads the whole line cleanly, with no restart. Write options.json here:\n"
            '{"options": [{"rel": "<recording from transcripts.json>", "start": <seconds>, "end": <seconds>, "why": "<one plain sentence>"}]}\n'
            "Use only recordings and times that appear in transcripts.json. Write nowhere else.")


def import_found(work: str, name: str, ref: str, path: Path) -> tuple[bool, str]:
    """Claude's takes become spans of clips.json and candidates of the clip's script line, so Replace shows them like any other take."""
    ans = _read(path)
    clips = _read(WORK / work / f"{name}.clips.json")
    b = next((x for x in beat_data(work, name)["beats"] if x["id"] == ref), None)
    if not isinstance(ans, dict) or not clips or not b or not b.get("script_lines"):
        return False, "Claude's answer could not be used."
    line = b["script_lines"][0]
    by_rel = {c["rel"]: c for c in clips["clips"]}
    cands = clips.setdefault("by_line", {}).setdefault(line, {"candidates": [], "picked": None})
    cands.setdefault("candidates", [])
    chunks = transcript_chunks(work, name)
    added = 0
    for o in ans.get("options") or []:
        try:
            rel, a, z = o["rel"], float(o["start"]), float(o["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if rel not in by_rel or not 0 <= a < z or z - a < TRIM_MIN:
            continue
        sid = clipmap.span_id(rel, a)
        if any(sid == sp["id"] for c in clips["clips"] for sp in c["spans"]):
            continue
        said = " ".join(c["text"] for c in chunks if c["rel"] == rel and c["end"] > a and c["start"] < z)
        by_rel[rel]["spans"].append({"id": sid, "start": round(a, 2), "end": round(z, 2), "dur": round(z - a, 2), "text": said, "script_lines": [line],
                                     "coverage": {line: 0.8}, "restarts": 0, "flags": ["found by Claude"], "confidence": 0.5, "topic": "", "summary": "",
                                     "skip": False, "note": str(o.get("why", ""))[:200], "edited": False})
        cands["candidates"].append(sid)
        added += 1
    if not added:
        return False, "Claude found no other take."
    clipmap.write_json(WORK / work / f"{name}.clips.json", clips)
    return True, f"Claude found {added} more take{'s' if added != 1 else ''}."
