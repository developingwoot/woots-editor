"""Teaching moments for the rough cut screen (ADR 0007): terms a first-time viewer needs explained, each with a yes / no from the host.

`<name>.teaching.json` (a plan file): {"moments": [{"id": "m1", "beat": "B07", "term": "pressure advance", "why": "one plain sentence",
  "source": "outline|claude", "status": "suggested|yes|no"}]}. The time on screen is the clip's time in the current cut (beat -> start).
Seeded from the voice-over beats of the beat map (the outline's teaching points); Claude can add more by reading the transcript.
The yes ones go into the preview's graphics plan (accepted()).
"""
import json
from pathlib import Path

import config
import projectstore

WORK = config.WORK


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.teaching.json"


def _beats(work: str, name: str) -> list:
    try:
        return json.loads((WORK / work / f"{name}.beatmap.json").read_text(encoding="utf-8-sig")).get("beats", [])
    except (OSError, ValueError):
        return []


def load(work: str, name: str) -> list:
    try:
        return json.loads(path(work, name).read_text(encoding="utf-8-sig")).get("moments", [])
    except (OSError, ValueError):
        return []


def save(work: str, name: str, moments: list):
    projectstore.write_json(path(work, name), {"moments": moments})


def seed(work: str, name: str) -> list:
    """Add a suggestion for every teaching voice-over (beat id TP..) that has none yet. Returns the moments."""
    moments = load(work, name)
    have = {m["beat"] for m in moments}
    added = False
    for b in _beats(work, name):
        if b["id"].startswith("TP") and not b.get("skip") and b["id"] not in have:
            term = ((b.get("vo") or {}).get("term") or b.get("user_note") or b.get("said") or "this").strip()
            moments.append({"id": f"m{len(moments) + 1}", "beat": b["id"], "term": term[:80],
                            "why": (b.get("why") or "The outline has a teaching point here").strip(), "source": "outline", "status": "suggested"})
            added = True
    if added:
        save(work, name, moments)
    return moments


def set_status(work: str, name: str, mid: str, status: str):
    if status not in ("yes", "no", "suggested"):
        raise ValueError("unknown answer")
    moments = load(work, name)
    for m in moments:
        if m["id"] == mid:
            m["status"] = status
    save(work, name, moments)


def accepted(work: str, name: str) -> list:
    return [m for m in load(work, name) if m["status"] == "yes"]


def find_prompt(work: str, name: str, fd: Path) -> str:
    """Claude reads the transcript text of each clip (beats.json) and suggests terms a first-time viewer needs explained."""
    fd.mkdir(parents=True, exist_ok=True)
    rows = [{"beat": b["id"], "said": b.get("said", "")} for b in _beats(work, name) if b.get("said") and not b.get("skip")]
    (fd / "beats.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    known = [m["term"] for m in load(work, name)]
    (fd / "known.json").write_text(json.dumps(known), encoding="utf-8")
    return ("beats.json is what the host says in each clip of his video. A first-time viewer does not know technical terms. "
            "Find up to 6 terms or ideas that need a short explanation (skip the ones in known.json). Write teaching.json here:\n"
            '{"moments": [{"beat": "<beat id from beats.json>", "term": "<the term>", "why": "<one plain sentence: why a newcomer needs it>"}]}\n'
            "Write nowhere else.")


def import_found(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        found = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("moments", [])
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    beats = {b["id"] for b in _beats(work, name)}
    moments = load(work, name)
    n = 0
    for f in found:
        if isinstance(f, dict) and f.get("beat") in beats and str(f.get("term", "")).strip():
            moments.append({"id": f"m{len(moments) + 1}", "beat": f["beat"], "term": str(f["term"]).strip()[:80],
                            "why": str(f.get("why", "")).strip()[:200], "source": "claude", "status": "suggested"})
            n += 1
    if n:
        save(work, name, moments)
    return n > 0, f"Claude found {n} more teaching moment{'s' if n != 1 else ''}." if n else "Claude found nothing to add."
