"""Tags on footage: the user watches a clip and says what is on screen for a range of it ("Fluidd dashboard, console tab").

`<name>.tags.json` (a plan file, so every change is recorded and undoable):
  {"next": 4, "tags": [{"id": 3, "rel": "Fluidd/Console_1.mkv", "start": 12.0, "end": 31.5, "label": "Fluidd dashboard, console tab", "note": "", "at": "2026-10-30T12:00:00"}]}
A tag always wins over the vision model's description: footage search reads a tagged moment as its label (brolllib.search), the cutaway
audit and the Claude briefs show the label, and a clip with little data is flagged so the important ones get tagged.
"""
import json
import time
from pathlib import Path

import config
import projectstore

WORK = config.WORK
THIN_SAMPLES = 2                                   # a clip longer than THIN_LONG_S described by fewer moments than this has little data
THIN_LONG_S = 20


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.tags.json"


def _read(work: str, name: str) -> dict:
    try:
        d = json.loads(path(work, name).read_text(encoding="utf-8-sig"))
        if isinstance(d, dict) and isinstance(d.get("tags"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"next": 1, "tags": []}


def load(work: str, name: str) -> list:
    return sorted(_read(work, name)["tags"], key=lambda t: (t["rel"], t["start"]))


def _save(work: str, name: str, d: dict, why: str):
    projectstore.write_json(path(work, name), d, who="user", why=why)


def _clean(rel, start, end, label, note="", length=None) -> dict:
    rel = str(rel or "").replace("\\", "/").strip()
    label = " ".join(str(label or "").split())
    if not rel:
        raise ValueError("choose a clip")
    if not label:
        raise ValueError("say what is on screen")
    try:
        start, end = round(float(start), 2), round(float(end), 2)
    except (TypeError, ValueError):
        raise ValueError("the start and end must be seconds")
    if start < 0 or end <= start:
        raise ValueError("the end must come after the start")
    if length and start >= length:
        raise ValueError("that range is past the end of the clip")
    return {"rel": rel, "start": start, "end": min(end, length) if length else end, "label": label[:200], "note": str(note or "").strip()[:500]}


def add(work: str, name: str, rel, start, end, label, note="", length=None) -> dict:
    d = _read(work, name)
    t = {"id": d.get("next", 1), **_clean(rel, start, end, label, note, length), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d["next"] = t["id"] + 1
    d["tags"].append(t)
    _save(work, name, d, f"tag {t['rel']}: {t['label']}")
    return t


def update(work: str, name: str, tag_id: int, **fields) -> dict:
    d = _read(work, name)
    t = next((x for x in d["tags"] if x["id"] == tag_id), None)
    if not t:
        raise ValueError("that tag is gone")
    t.update(_clean(t["rel"], fields.get("start", t["start"]), fields.get("end", t["end"]), fields.get("label", t["label"]), fields.get("note", t.get("note", ""))))
    _save(work, name, d, f"edit tag {t['rel']}: {t['label']}")
    return t


def delete(work: str, name: str, tag_id: int):
    d = _read(work, name)
    gone = [x for x in d["tags"] if x["id"] == tag_id]
    if not gone:
        raise ValueError("that tag is gone")
    d["tags"] = [x for x in d["tags"] if x["id"] != tag_id]
    _save(work, name, d, f"remove tag {gone[0]['rel']}: {gone[0]['label']}")


def at(tags: list, rel: str, t: float) -> dict | None:
    """The tag covering second `t` of clip `rel` (the narrowest when several), or None."""
    hit = [x for x in tags if x["rel"] == rel and x["start"] <= t < x["end"]]
    return min(hit, key=lambda x: x["end"] - x["start"]) if hit else None


def by_clip(tags: list) -> dict:
    out = {}
    for x in tags:
        out.setdefault(x["rel"], []).append(x)
    return out


def thin(clip: dict | None, dur: float | None) -> bool:
    """True when the vision library has little to say about a clip: not looked at, failed, or a long clip described from a moment or two."""
    if not clip or clip.get("error") or not clip.get("samples"):
        return True
    return len(clip["samples"]) < THIN_SAMPLES and (dur or clip.get("dur") or 0) > THIN_LONG_S
