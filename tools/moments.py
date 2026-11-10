"""Fun moments for the rough cut screen (C4): a very short pop-up that makes a good line land (a sticker on a joke, a number that jumps), each with a yes / no from the host.

`<name>.moments.json` (a plan file): {"moments": [{"id": "f1", "beat": "B07", "kind": "stamp|burst|counter|kinetic", "text": "THREE WEEKS", "why": "one plain sentence", "status": "suggested|yes|no"}]}
Claude suggests them from what the host says (find_prompt / import_found); the limits are the host's (youtube-graphics/graphics.json): at most `moments_per_min_max` a minute,
at least `moment_gap_s` between two, none longer than `moment_max_s`. Never on a beat that has a teaching moment (a yes) or already has a graphic.
A yes puts a pop-up graphic on the beat (set_status); a change of mind takes it off again. Nothing is built until the next preview.
"""
import json
from pathlib import Path

import beatmap
import config
import projectstore
import skillrules
import teaching

WORK = config.WORK
KINDS = ("stamp", "burst", "counter", "kinetic")


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.moments.json"


def load(work: str, name: str) -> list:
    try:
        return json.loads(path(work, name).read_text(encoding="utf-8-sig")).get("moments", [])
    except (OSError, ValueError, AttributeError):
        return []


def save(work: str, name: str, moments: list):
    projectstore.write_json(path(work, name), {"moments": moments})


def _bm(work: str, name: str) -> dict:
    try:
        return json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"beats": []}


def allowed(work: str, name: str, count_new: int | None = None) -> int:
    """How many fun moments this cut may have in all: the per-minute limit times the runtime (at least one)."""
    beats = [b for b in _bm(work, name).get("beats", []) if not b.get("skip")]
    minutes = sum(float(b.get("dur") or 0) for b in beats) / 60.0
    return max(1, int(minutes * skillrules.graphics()["moments_per_min_max"]))


def find_prompt(work: str, name: str, fd: Path) -> str:
    fd.mkdir(parents=True, exist_ok=True)
    teach = {m["beat"] for m in teaching.load(work, name)}
    rows = [{"beat": b["id"], "start": round(float(b.get("start") or 0), 1), "said": b.get("said", "")}
            for b in _bm(work, name).get("beats", []) if b.get("said") and not b.get("skip") and not b.get("graphic") and b["id"] not in teach]
    (fd / "beats.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    r = skillrules.graphics()
    got = skillrules.copy_into(fd, "moments")
    return ("beats.json is what the host says in each clip of the host's video. " + skillrules.read_first_line(got) + "moments.md holds the rules for this job.\n"
            f"Pick the lines where a very short pop-up would make a good line land: at most {allowed(work, name)} in the whole video, at least {r['moment_gap_s']:g} seconds apart, "
            f"each lasting at most {r['moment_max_s']:g} seconds. Write moments.json here:\n"
            '{"moments": [{"beat": "<beat id from beats.json>", "kind": "stamp|burst|counter|kinetic", "text": "<one to four words shown on screen>", "why": "<one plain sentence>"}]}\n'
            "Write nowhere else.")


def import_found(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        found = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("moments", [])
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    bm = _bm(work, name)
    by = {b["id"]: b for b in bm.get("beats", [])}
    teach = {m["beat"] for m in teaching.accepted(work, name)}
    moments = load(work, name)
    r = skillrules.graphics()
    room = allowed(work, name) - len([m for m in moments if m["status"] != "no"])
    taken = [float(by[m["beat"]].get("start") or 0) for m in moments if m["status"] != "no" and m["beat"] in by]
    n = 0
    for f in found:
        if not isinstance(f, dict) or n >= room:
            continue
        b = by.get(f.get("beat"))
        text = " ".join(str(f.get("text", "")).split())[:40]
        if not b or b.get("skip") or b.get("graphic") or b["id"] in teach or not text or f.get("kind") not in KINDS:
            continue
        if any(m["beat"] == b["id"] for m in moments):
            continue
        t = float(b.get("start") or 0)
        if any(abs(t - x) < r["moment_gap_s"] for x in taken):
            continue
        moments.append({"id": f"f{len(moments) + 1}", "beat": b["id"], "kind": f["kind"], "text": text, "why": str(f.get("why", "")).strip()[:200], "status": "suggested"})
        taken.append(t)
        n += 1
    if n:
        save(work, name, moments)
    return n > 0, f"Claude found {n} fun moment{'s' if n != 1 else ''}." if n else "Claude found nothing to add."


def set_status(work: str, name: str, mid: str, status: str):
    """yes puts the pop-up on the beat; any other answer takes it off again (only a pop-up this module put there)."""
    if status not in ("yes", "no", "suggested"):
        raise ValueError("unknown answer")
    moments = load(work, name)
    m = next((x for x in moments if x["id"] == mid), None)
    if not m:
        raise ValueError("there is no such moment")
    bm = _bm(work, name)
    b = next((x for x in bm.get("beats", []) if x["id"] == m["beat"]), None)
    if b is not None:
        if status == "yes" and not b.get("graphic"):
            r = skillrules.graphics()
            b["graphic"] = {"kind": m["kind"], "text": m["text"], "dur": r["moment_max_s"], "words": b.get("said", "")[:80], "idea": m["why"],
                            "why": m["why"], "strength": 3, "struck": False, "fun": True}
            projectstore.write_json(beatmap.path_of(work, name), bm, why="fun moment added")
        elif status != "yes" and (b.get("graphic") or {}).get("fun"):
            b["graphic"] = None
            projectstore.write_json(beatmap.path_of(work, name), bm, why="fun moment removed")
    m["status"] = status
    save(work, name, moments)


def accepted(work: str, name: str) -> list:
    return [m for m in load(work, name) if m["status"] == "yes"]
