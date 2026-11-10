"""Graphics plan and graphics review: the host can choose the LOOK of each graphic before it is built, then check each built graphic in context.

The beat map says which graphics exist and why. This module keeps the host's design decisions on top of it, so the beat map never changes:
  <name>.graphicsplan.json    {"version":1, "created", "gfx_sig", "decisions": {beat_id: {"style": "depth", "note": "...", "status": "ok|change|cut"}}}
  <name>.graphicsreview.json  {"version":1, "created", "marks": {beat_id: {"status": "ok|change", "note": "...", "built_sig": "...", "t": "..."}}}
`apply()` lays those decisions onto the beat map IN MEMORY (style, a design note, the host's change request after he saw the built graphic, and "cut" = struck), so the build plan, the brief
for the background Claude run and the design signature (which says a built graphic is out of date) all see them. A change request after a review makes the graphic "not built" again,
so the Build board offers a rebuild whose brief carries his note. Pure Python; it imports the other tools lazily.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

TOOLS = Path(os.path.abspath(__file__)).parent
EDITOR = TOOLS.parent
import config
WORK = config.WORK
sys.path.insert(0, str(TOOLS))

STYLES = [
    {"id": "brand", "label": "Plain brand card", "desc": "Navy and orange, Oswald Bold headline, calm and clean. The safe default."},
    {"id": "depth", "label": "3D depth and camera move", "desc": "Layers at different depths with a slow camera move or parallax, so the graphic feels like a space."},
    {"id": "sticker", "label": "Comic sticker caption", "desc": "A bold caption that pops on like a sticker with a springy bounce."},
    {"id": "ui", "label": "Clean product-UI explainer", "desc": "A flat, tidy interface-style diagram; the parts light up one at a time as they are named."},
    {"id": "kinetic", "label": "Kinetic type", "desc": "The words themselves move and land on the beat."},
]
STYLE_IDS = {s["id"] for s in STYLES}


def _replace(tmp, p):
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
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data, who=None):
    projectstore.write_json(p, data, who)


def wd_of(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work:
        raise ValueError(f"bad name {work!r}")
    d = WORK / work
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def plan_path(work, name) -> Path:
    return wd_of(work) / f"{name}.graphicsplan.json"


def review_path(work, name) -> Path:
    return wd_of(work) / f"{name}.graphicsreview.json"


def _beatmap(work, name) -> dict | None:
    return read_json(wd_of(work) / f"{name}.beatmap.json")


def graphic_beats(bm: dict) -> list[dict]:
    """Beats with a graphic that has not been struck in the beat map (title and end cards included)."""
    return [b for b in bm.get("beats", []) if b.get("graphic") and not b["graphic"].get("struck") and not b.get("skip")]


def gfx_sig(bm: dict) -> str:
    key = [(b["id"], {k: b["graphic"].get(k) for k in ("kind", "idea", "words", "text", "dur")}) for b in graphic_beats(bm)]
    return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def apply(work: str, name: str, bm: dict) -> dict:
    """Lay the host's decisions onto the beat map in memory (never written back)."""
    try:
        plan = read_json(plan_path(work, name), {}) or {}
        rev = read_json(review_path(work, name), {}) or {}
    except ValueError:
        return bm
    dec, marks = plan.get("decisions", {}), rev.get("marks", {})
    for b in bm.get("beats", []):
        g = b.get("graphic")
        if not g:
            continue
        d = dec.get(b["id"]) or {}
        if d.get("style") in STYLE_IDS:
            g["style"] = d["style"]
        if d.get("note"):
            g["plan_note"] = d["note"]
        if d.get("status") == "cut":
            g["struck"] = True
        m = marks.get(b["id"]) or {}
        if m.get("note") and (m.get("status") == "change" or m.get("keep_note")):      # keep_note: he marked it OK after it was rebuilt WITH this note
            g["review_note"] = m["note"]
    return bm


# ----------------------------------------------------------------------------- the plan (before the build)
def ensure_plan(work: str, name: str) -> dict | None:
    bm = _beatmap(work, name)
    if not bm:
        return None
    p = plan_path(work, name)
    j = read_json(p)
    if j is None:
        j = {"version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "gfx_sig": gfx_sig(bm), "decisions": {}}
        write_json(p, j, who="auto")
    return j


def state(work: str, name: str) -> dict:
    bm = _beatmap(work, name)
    out = {"work": work, "name": name, "beatmap_ready": bool(bm), "exists": False, "styles": STYLES, "cards": [], "counts": {}, "warnings": [], "stale": False}
    if not bm:
        return out
    j = ensure_plan(work, name)
    out["exists"] = True
    dec = j.get("decisions", {})
    stills = {}
    try:
        import storyboard
        for f in storyboard.state(work, name)["frames"]:
            stills[f["id"]] = f.get("img")
    except Exception:
        pass
    cards = []
    for b in bm["beats"]:
        g = b.get("graphic")
        if not g or g.get("struck") or b.get("skip"):
            continue
        d = dec.get(b["id"]) or {}
        card = g.get("kind") in ("title", "end")
        cards.append({"beat": b["id"], "section": b.get("section", ""), "kind": g.get("kind"), "is_card": card, "idea": g.get("idea", ""), "words": g.get("words", ""),
                      "text": g.get("text", ""), "dur": g.get("dur"), "why": g.get("why", ""), "strength": g.get("strength"), "said": (b.get("said") or "")[:160],
                      "start": b.get("start"), "still": stills.get(b["id"]), "style": d.get("style", ""), "note": d.get("note", ""), "status": d.get("status", "")})
    out["cards"] = cards
    n = len(cards)
    out["counts"] = {"graphics": sum(1 for c in cards if c["kind"] not in ("title", "end", "counter", "stamp", "burst", "kinetic")),
                     "popups": sum(1 for c in cards if c["kind"] in ("counter", "stamp", "burst", "kinetic")), "cards": sum(1 for c in cards if c["is_card"]), "all": n, "styled": sum(1 for c in cards if c["style"]), "ok": sum(1 for c in cards if c["status"] == "ok"),
                     "change": sum(1 for c in cards if c["status"] == "change"), "cut": sum(1 for c in cards if c["status"] == "cut"),
                     "undecided": sum(1 for c in cards if not c["status"])}
    out["stale"] = j.get("gfx_sig") != gfx_sig(bm)
    if out["stale"]:
        out["warnings"].append("the graphics in the beat map changed since you last looked at this plan: look again, then press 'I've seen the changes'")
    if out["counts"]["undecided"]:
        out["warnings"].append(f"{out['counts']['undecided']} graphic{'s' if out['counts']['undecided'] != 1 else ''} not marked OK, needs a change, or cut yet")
    if out["counts"]["change"]:
        out["warnings"].append(f"{out['counts']['change']} marked 'needs a change': tell Claude what to adjust, or fix the note and mark it OK")
    out["gfx_sig"] = j.get("gfx_sig")
    return out


def plan_op(work: str, name: str, op: str, b: dict) -> dict:
    j = ensure_plan(work, name)
    if j is None:
        raise ValueError("there is no beat map yet")
    bm = _beatmap(work, name)
    if op == "set":
        bid = b.get("beat")
        if bid not in {x["id"] for x in graphic_beats(bm)}:
            raise ValueError(f"beat {bid!r} has no graphic")
        d = j["decisions"].setdefault(bid, {})
        if "style" in b:
            if b["style"] not in STYLE_IDS and b["style"] != "":
                raise ValueError("unknown look")
            d["style"] = b["style"]
        if "note" in b:
            d["note"] = " ".join(str(b["note"]).split())[:600]
        if "status" in b:
            if b["status"] not in ("", "ok", "change", "cut"):
                raise ValueError("status must be ok, change, cut or empty")
            d["status"] = b["status"]
    elif op == "ack":
        j["gfx_sig"] = gfx_sig(bm)
    else:
        raise ValueError(f"unknown operation {op!r}")
    write_json(plan_path(work, name), j)
    return state(work, name)


# ----------------------------------------------------------------------------- the review (after the build)
def _built(work, name) -> dict:
    try:
        import sections
        return sections.load_built(work, name)
    except Exception:
        return {}


def ensure_review(work: str, name: str) -> dict | None:
    if not _beatmap(work, name):
        return None
    j = read_json(review_path(work, name))
    if j is None:
        j = {"version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "marks": {}}
        write_json(review_path(work, name), j, who="auto")
    return j


def review_state(work: str, name: str) -> dict:
    bm = _beatmap(work, name)
    out = {"work": work, "name": name, "beatmap_ready": bool(bm), "exists": False, "cards": [], "counts": {}, "warnings": [], "preview": None}
    if not bm:
        return out
    j = ensure_review(work, name)
    out["exists"] = True
    apply(work, name, bm)
    built = _built(work, name)
    try:
        import sections
        import watchnotes
        pf = watchnotes.preview_file(work, name)
        out["preview"] = {"file": pf.name, "mtime": int(pf.stat().st_mtime)} if pf.exists() else None
    except Exception:
        sections = None
    segs = []
    if out["preview"]:
        try:
            import selfreview
            segs = selfreview.timeline(work, name)["segments"]
        except Exception:
            segs = []
    marks = j.get("marks", {})
    cards = []
    for b in bm["beats"]:
        g = b.get("graphic")
        if not g or g.get("struck") or b.get("skip"):
            continue
        base = sections.gsig({k: v for k, v in g.items() if k != "review_note"}) if sections else ""      # the design as it was when the creator looked
        is_built = bool(sections and sections.graphic_built(g, b["id"], built))
        seg = next((s for s in segs if (s.get("beat") or s.get("id")) == b["id"]), None)
        m = marks.get(b["id"]) or {}
        rebuilt = m.get("status") == "change" and is_built                    # built again after his change request: he must look again
        seen = m.get("status") in ("ok", "change") and m.get("built_sig") == base and not rebuilt
        cards.append({"beat": b["id"], "section": b.get("section", ""), "kind": g.get("kind"), "idea": g.get("idea", ""), "text": g.get("text", ""), "words": g.get("words", ""),
                      "style": g.get("style", ""), "plan_note": g.get("plan_note", ""), "built": is_built, "t": seg["start"] if seg else None, "dur": seg["dur"] if seg else g.get("dur"),
                      "status": m.get("status", "") if seen else "", "note": m.get("note", ""), "rebuilt": rebuilt,
                      "looked_at_older": bool(m) and not seen and is_built and not rebuilt})
    out["cards"] = cards
    out["counts"] = {"graphics": len(cards), "built": sum(1 for c in cards if c["built"]), "ok": sum(1 for c in cards if c["status"] == "ok"),
                     "change": sum(1 for c in cards if c["status"] == "change"), "unseen": sum(1 for c in cards if c["built"] and not c["status"])}
    if cards and out["counts"]["built"] < len(cards):
        out["warnings"].append(f"{len(cards) - out['counts']['built']} graphic(s) not built yet (Build tab)")
    if out["counts"]["unseen"]:
        out["warnings"].append(f"{out['counts']['unseen']} built graphic(s) you have not looked at yet")
    if out["counts"]["change"]:
        out["warnings"].append(f"{out['counts']['change']} graphic(s) marked 'needs a change': rebuild that section in the Build tab so Claude applies your note")
    if cards and not out["preview"]:
        out["warnings"].append("there is no stitched preview yet, so graphics cannot be played in context")
    return out


def review_op(work: str, name: str, op: str, b: dict) -> dict:
    j = ensure_review(work, name)
    if j is None:
        raise ValueError("there is no beat map yet")
    if op != "mark":
        raise ValueError(f"unknown operation {op!r}")
    bm = _beatmap(work, name)
    apply(work, name, bm)
    bid = b.get("beat")
    beat = next((x for x in graphic_beats(bm) if x["id"] == bid), None)
    if not beat:
        raise ValueError(f"beat {bid!r} has no graphic")
    status = b.get("status", "")
    if status not in ("", "ok", "change"):
        raise ValueError("status must be ok, change or empty")
    if status == "change" and len(" ".join(str(b.get("note", "")).split())) < 3:
        raise ValueError("say what should change: Claude uses your note to rebuild it")
    import sections
    prev = j["marks"].get(bid) or {}
    keep = status == "ok" and prev.get("status") in ("change",) and bool(prev.get("note"))        # the graphic was (or will be) built with that note: it stays part of its design
    if status:
        j["marks"][bid] = {"keep_note": keep, "status": status, "note": (prev["note"] if keep else " ".join(str(b.get("note", "")).split())[:600]), "built_sig": sections.gsig({k: v for k, v in beat["graphic"].items() if k != "review_note"}), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    else:
        j["marks"].pop(bid, None)
    write_json(review_path(work, name), j)
    return review_state(work, name)


if __name__ == "__main__":
    print(json.dumps(state(sys.argv[1], sys.argv[2]), indent=1)[:2500])
