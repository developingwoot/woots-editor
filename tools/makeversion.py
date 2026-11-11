"""Make preview N+1 from the notes (ADR 0007): the pure parts of the job. The server runs them in order:
  1. brief()        - what Claude is asked, with the notes and a copy of the plan to edit (in a scratch folder)
  2. apply_answer() - read Claude's answer, write the edited beat map through projectstore, report what it did
  3. (server)       - rebuild the changed sections and stitch (a fake copy of the preview in tests)
  4. finish()       - record the new video as the next version, the applied notes become 'done in <version>'
"""
import json
import re
import time
from pathlib import Path

import config
import projectstore
import reviewnotes
import views

WORK = config.WORK


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def preview_file(work: str, name: str) -> Path | None:
    import watchnotes
    p = watchnotes.preview_file(work, name)
    return p if p.exists() else None


def clips_of(work: str, name: str) -> list:
    """The clips of the current preview in order: [{start, dur}] (seconds). From the section renders when they exist, else the stitched sections."""
    try:
        import selfreview
        segs = selfreview.timeline(work, name)["segments"]
        if segs:
            return [{"start": round(s["start"], 2), "dur": round(s["dur"], 2)} for s in segs]
    except Exception:                       # noqa: BLE001  (no section renders: fall back to the sections)
        pass
    stitch = read_json(WORK / work / f"{name}.stitch.json", {}) or {}
    return [{"start": s["start"], "dur": s["dur"]} for s in stitch.get("sections", [])]


def ensure_baseline(work: str, name: str, stage: str = "preview"):
    """The preview that exists before any version was made becomes version 1, so the first make has something to compare with."""
    src = preview_file(work, name)
    if src and not reviewnotes.versions(work, name, stage):
        reviewnotes.add_version(work, name, stage, src, ["The first version"], clips_of(work, name))


def plain_notes(work: str, name: str, stage: str) -> list:
    """The open free-text notes: the ones Claude applies. Exact choices on a clip (replace, remove, trim) are applied by code."""
    return [n for n in reviewnotes.open_notes(work, name, stage) if n.get("kind", "note") in ("note", "continuity")]


def brief(work: str, name: str, stage: str, fd: Path) -> str:
    """Write the notes and the plan into fd and return the prompt. Claude answers in answer.json (see apply_answer)."""
    fd.mkdir(parents=True, exist_ok=True)
    notes = [({"id": n["id"], "time": "whole video", "until": None, "note": n["text"]} if n.get("whole") else
              {"id": n["id"], "time": views.time_text(n["t"]), "until": views.time_text(n["t_end"]) if n.get("t_end") is not None else None, "note": n["text"]})
             for n in plain_notes(work, name, stage)]
    (fd / "notes.json").write_text(json.dumps(notes, indent=1), encoding="utf-8")
    bm = read_json(WORK / work / f"{name}.beatmap.json")
    if bm is not None:
        (fd / "beatmap.json").write_text(json.dumps(bm, indent=1), encoding="utf-8")
    return (
        f"The host watched the {'rough cut' if stage == 'cut' else 'preview'} of the host's video and left notes (notes.json, times are minutes:seconds into the video).\n"
        "A note whose time is \"whole video\" is about the video as a whole (for example: too long, cut more, be pickier). Apply it across the plan: set `skip` on the weakest beats (never a beat the host marked good), "
        "shorten, or tighten as the note asks, and say in the summary what you did overall.\n"
        "beatmap.json is the plan the video is built from. For each note, decide whether a change to the beat map makes the video match what the host asked.\n"
        "Write answer.json in this folder:\n"
        '{"applied": [{"id": <note id>, "summary": "<one plain sentence about what you changed, no ids or file names>"}],\n'
        ' "skipped": [{"id": <note id>, "why": "<one plain sentence>"}],\n'
        ' "lesson": "<optional: ONE general sentence, no times and no video names, only when a note taught something that applies to other videos>",\n'
        ' "beatmap": <the whole edited beat map, only if you changed it>}\n'
        "Change as little as possible. Keep every field you do not need to change exactly as it is. Do not write anywhere else.")


def apply_answer(work: str, name: str, stage: str, path: Path) -> tuple[bool, str, dict]:
    """Returns (ok, message, result) with result = {applied_ids, changes}. The beat map is only replaced by a well-formed one."""
    ans = read_json(path)
    if not isinstance(ans, dict):
        return False, "Claude's answer could not be read.", {}
    open_ids = {n["id"] for n in plain_notes(work, name, stage)}
    applied = [a for a in ans.get("applied") or [] if isinstance(a, dict) and a.get("id") in open_ids and str(a.get("summary", "")).strip()]
    if not applied:
        return False, "Claude could not apply any of the notes.", {}
    bm = ans.get("beatmap")
    if bm is not None:
        if not isinstance(bm, dict) or not isinstance(bm.get("beats"), list):
            return False, "Claude's edited plan was not usable, so nothing was changed.", {}
        projectstore.write_json(WORK / work / f"{name}.beatmap.json", bm, why="notes applied")
    changes = [" ".join(str(a["summary"]).split())[:200] for a in applied]
    n_skipped = len([s for s in ans.get("skipped") or [] if isinstance(s, dict)])
    msg = f"Applied {len(applied)} note{'s' if len(applied) != 1 else ''}" + (f"; {n_skipped} could not be applied." if n_skipped else ".")
    return True, msg, {"applied_ids": [a["id"] for a in applied], "changes": changes, "lesson": clean_lesson(ans.get("lesson"))}


def clean_lesson(x) -> str:
    """One general sentence: no times, no ids, not long. Anything else is not offered."""
    t = " ".join(str(x or "").split())
    if not 12 <= len(t) <= 240 or re.search(r"\d+:\d\d|\b[SBG]\d{2}\b", t):
        return ""
    return t


def finish_cut(work: str, name: str, video: Path, rows: list, result: dict) -> dict:
    """The rendered rough cut becomes the next version. `result` = {applied_ids, changes}; the first cut has none."""
    changes = result.get("changes") or (["The first cut"] if not reviewnotes.versions(work, name, "cut") else ["Made again, nothing changed"])
    clips = [{"start": r["start"], "dur": r["dur"], "ref": r["ref"]} for r in rows]
    return reviewnotes.add_version(work, name, "cut", video, changes, clips, result.get("applied_ids"), result.get("suggestions"), result.get("lesson", ""))


def finish(work: str, name: str, stage: str, result: dict) -> dict:
    src = preview_file(work, name)
    if not src:
        raise ValueError("there is no new video to keep")
    return reviewnotes.add_version(work, name, stage, src, result["changes"], clips_of(work, name), result["applied_ids"], lesson=result.get("lesson", ""))


def fake_stitch(work: str, name: str):
    """Tests (WOOTS_FAKE_CLAUDE set): no section builds, a copy of the current preview under a new name becomes the stitched preview."""
    import shutil
    import watchnotes
    src = watchnotes.preview_file(work, name)
    if not src.exists():
        raise ValueError("there is no preview to start from")
    dst = src.with_name(f"{name}.preview-half.fake{int(time.time() * 1000)}.mp4")
    shutil.copyfile(src, dst)
    st = read_json(WORK / work / f"{name}.stitch.json", {}) or {}
    st["file"] = dst.name
    projectstore.atomic_write(WORK / work / f"{name}.stitch.json", json.dumps(st, indent=1).encode("utf-8"))
