"""Watch & note: the host watches the whole half-size video (stage 7, gate E) and pins notes to the exact moment.

Replaces the old Review tab for videos made with the new workflow (the old tab only lists videos with an edit.json).
Notes live in `<name>.watchnotes.json`:
  {"notes": [{"id": 1, "t": 12.34, "frame": 370, "text": "...", "status": "open|done",
              "section": "S2", "beat": "B07", "line": "S05", "said": "what is said there", "created": "2026-10-23T09:12:00"}]}
`t` is seconds into `<name>.preview-half.mp4` (the stitched preview); the beat, script line and words are looked up from the stitch
timeline and the beat map so Claude can act on a note without guessing from a time code. `preview_sig` records which preview the
note was made on; a note from an older preview is flagged "older preview".
Pure Python, imports the other tools lazily.
"""
import json
import os
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
EDITOR = TOOLS.parent
import config
WORK = config.WORK
sys.path.insert(0, str(TOOLS))
FPS = 30


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


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def wd_of(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work:
        raise ValueError(f"bad name {work!r}")
    d = WORK / work
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def notes_path(work, name) -> Path:
    return wd_of(work) / f"{name}.watchnotes.json"


def preview_file(work, name) -> Path:
    try:                                                          # every stitch has its own file name (a player holding the old one open no longer blocks a new stitch)
        f = json.loads((wd_of(work) / f"{name}.stitch.json").read_text(encoding="utf-8-sig")).get("file")
        if f and (wd_of(work) / f).exists():
            return wd_of(work) / f
    except (OSError, ValueError):
        pass
    return wd_of(work) / f"{name}.preview-half.mp4"


def preview_sig(work, name) -> str | None:
    p = preview_file(work, name)
    if not p.exists():
        return None
    st = p.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def locate(work, name, t: float) -> dict:
    """Which section, beat, script line and spoken words are on screen at time t of the stitched preview."""
    out = {"section": None, "beat": None, "line": None, "said": None}
    stitch = read_json(wd_of(work) / f"{name}.stitch.json")
    if stitch:
        for s in stitch.get("sections", []):
            if s["start"] - 1e-6 <= t < s["start"] + (s.get("dur") or 0) + 1e-6:
                out["section"] = s["id"]
    try:
        import selfreview
        seg = selfreview.seg_at(t, selfreview.timeline(work, name)["segments"])
        if seg:
            out["beat"] = seg.get("beat") or seg.get("id")
    except Exception:
        pass
    bm = read_json(wd_of(work) / f"{name}.beatmap.json", {}) or {}
    if out["beat"]:
        b = next((x for x in bm.get("beats", []) if x.get("id") == out["beat"]), None)
        if b:
            out["line"] = b.get("script_line")
            out["said"] = (b.get("said") or "")[:200]
    return out


def state(work: str, name: str) -> dict:
    wd = wd_of(work)
    pf = preview_file(work, name)
    j = read_json(notes_path(work, name), {"notes": []}) or {"notes": []}
    sig = preview_sig(work, name)
    notes = []
    for n in j.get("notes", []):
        notes.append({**n, "older": bool(sig and n.get("preview_sig") and n["preview_sig"] != sig)})
    stitch = read_json(wd / f"{name}.stitch.json")
    return {"work": work, "name": name, "exists": pf.exists(), "file": pf.name, "mtime": int(pf.stat().st_mtime) if pf.exists() else None,
            "dur": (stitch or {}).get("dur"), "stitched": (stitch or {}).get("stitched"), "notes": sorted(notes, key=lambda n: n["t"]),
            "open": sum(1 for n in notes if n.get("status") != "done"), "done": sum(1 for n in notes if n.get("status") == "done")}


def apply_op(work: str, name: str, op: str, b: dict) -> dict:
    p = notes_path(work, name)
    j = read_json(p, {"notes": []}) or {"notes": []}
    j.setdefault("notes", [])
    if op == "add":
        text = " ".join(str(b.get("text", "")).split())
        if len(text) < 2:
            raise ValueError("write the note first")
        t = float(b.get("t", 0))
        if not preview_file(work, name).exists():
            raise ValueError("there is no stitched preview yet: stitch the sections first")
        nid = 1 + max([n["id"] for n in j["notes"]] + [0])
        j["notes"].append({"id": nid, "t": round(t, 3), "frame": int(round(t * FPS)), "text": text[:800], "status": "open",
                           **locate(work, name, t), "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "preview_sig": preview_sig(work, name)})
    elif op in ("done", "reopen"):
        for n in j["notes"]:
            if n["id"] == b.get("id"):
                n["status"] = "done" if op == "done" else "open"
    elif op == "edit":
        for n in j["notes"]:
            if n["id"] == b.get("id"):
                n["text"] = " ".join(str(b.get("text", "")).split())[:800] or n["text"]
    elif op == "delete":
        j["notes"] = [n for n in j["notes"] if n["id"] != b.get("id")]
    else:
        raise ValueError(f"unknown operation {op!r}")
    write_json(p, j)
    return state(work, name)


if __name__ == "__main__":
    print(json.dumps(state(sys.argv[1], sys.argv[2]), indent=1)[:2000])
