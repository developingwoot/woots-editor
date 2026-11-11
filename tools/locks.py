"""Good / don't-touch marks on a cut: the host marks sentences of the rough cut as good, and no pass changes them when he asks for changes elsewhere.

`<name>.locks.json` (a plan file, so recorded and undoable): {"next": 3, "locks": [{"id": 2, "texts": ["normalized sentence", ...], "note": "", "at": "..."}]}
A mark is kept by the WORDS of its sentences (like `cutreview` drops), so it still holds when the cut is made again from the same recordings.
A beat with a locked sentence is a locked beat: the cut read and the takes read drop nothing from it, nothing is restored into it, and
B-roll, the cutaway audit and the zoom plan leave it exactly as it is. A rule that wanted to change one reports it ("locked, not changed").
"""
import json
import time
from pathlib import Path

import config
import projectstore

WORK = config.WORK


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.locks.json"


def _read(work: str, name: str) -> dict:
    try:
        d = json.loads(path(work, name).read_text(encoding="utf-8-sig"))
        if isinstance(d, dict) and isinstance(d.get("locks"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"next": 1, "locks": []}


def load(work: str, name: str) -> list:
    return _read(work, name)["locks"]


def texts(work: str, name: str) -> set:
    return {t for lk in load(work, name) for t in lk["texts"]}


def add(work: str, name: str, data: dict, ids: list, note: str = "") -> dict:
    """Lock the played sentences with these ids (as `transcript` lists them)."""
    by_id = {s["id"]: s for s in transcript(data)}
    picked = [by_id[i]["text"] for i in ids if i in by_id]
    if not picked:
        raise ValueError("choose at least one sentence of the cut")
    import cutreview
    d = _read(work, name)
    lk = {"id": d["next"], "texts": [cutreview.norm(t) for t in picked], "note": str(note or "").strip()[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d["next"] += 1
    d["locks"].append(lk)
    projectstore.write_json(path(work, name), d, who="user", why=f"mark {len(picked)} sentence{'s' if len(picked) != 1 else ''} as good")
    return lk


def unlock(work: str, name: str, lock_id: int, ids: list | None = None, data: dict | None = None):
    """Remove a whole mark, or only the given sentences from it (a mark with none left goes away)."""
    d = _read(work, name)
    lk = next((x for x in d["locks"] if x["id"] == lock_id), None)
    if not lk:
        raise ValueError("that mark is gone")
    if ids and data:
        import cutreview
        gone = {cutreview.norm(s["text"]) for s in transcript(data) if s["id"] in set(ids)}
        lk["texts"] = [t for t in lk["texts"] if t not in gone]
    else:
        lk["texts"] = []
    d["locks"] = [x for x in d["locks"] if x["texts"]]
    projectstore.write_json(path(work, name), d, who="user", why="take a good mark off")


def _talking(b: dict) -> bool:
    return bool(b.get("aroll")) and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H")


def transcript(data: dict) -> list:
    """Every sentence the cut plays, in order, with its place in the cut: [{id, beat, text, start, end}] (seconds in the cut)."""
    import cutreview
    out = []
    removed = 0.0                               # time of beats taken out (skip) whose later beats still hold their old start: not counted twice when the plan was retimed
    for b in data.get("beats", []):
        begin = float(b.get("start", 0.0)) - removed
        if b.get("skip"):
            removed += max(0.0, float(b.get("end", 0.0)) - float(b.get("start", 0.0)))
        if not _talking(b):
            continue
        ar = b["aroll"]
        keep = ar.get("keep") or [[ar["in"], ar["out"]]]
        starts, acc = [], begin
        for a, z in keep:
            starts.append((a, z, acc))
            acc += z - a

        def at(sec):
            for a, z, t0 in starts:
                if a - 0.001 <= sec <= z + 0.001:
                    return t0 + (sec - a)
            return starts[-1][2] + (starts[-1][1] - starts[-1][0])
        for n, (text, idx) in enumerate(cutreview.sentence_runs(b), 1):
            w = ar["words"]
            out.append({"id": f"{b['id']}.{n}", "beat": b["id"], "text": text, "start": round(at(w[idx[0]][1]), 2), "end": round(at(w[idx[-1]][2]), 2)})
    return out


def beat_ids(work: str, name: str, data: dict) -> set:
    """Ids of the beats that play a locked sentence."""
    import cutreview
    held = texts(work, name)
    if not held:
        return set()
    return {s["beat"] for s in transcript(data) if cutreview.norm(s["text"]) in held}


def view(work: str, name: str, data: dict) -> list:
    """The cut's transcript with each sentence's mark: [{id, text, start, end, lock}]."""
    import cutreview
    which = {}
    for lk in load(work, name):
        for t in lk["texts"]:
            which[t] = lk["id"]
    return [{**s, "lock": which.get(cutreview.norm(s["text"]))} for s in transcript(data)]
