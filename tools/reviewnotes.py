"""Notes and versions for the v2 review screen (ADR 0007): one store for the rough cut and the preview.

`<name>.notes.json`:
  {"cut": [note...], "preview": [note...],
   "versions": {"cut": [version...], "preview": [version...]}}
  note    = {"id": 1, "t": 42.0, "t_end": null, "text": "...", "clip": null, "kind": "note", "status": "open|done", "applied_in": null | version number}
  version = {"n": 2, "file": "<name>.preview-v2.mp4", "made": "2026-10-28T09:12:00", "changes": ["plain sentence", ...],
             "clips": [{"start": 0.0, "dur": 3.0}], "marker": "preview2"}
A version is a history marker (projectstore.mark), not an approval (ADR 0003, 0007). Old `<name>.watchnotes.json` notes are read once.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

import config
import projectstore

WORK = config.WORK
STAGES = ("cut", "preview")
LABEL = {"cut": "Cut", "preview": "Preview"}
_lock = threading.Lock()


def wd_of(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work:
        raise ValueError(f"bad name {work!r}")
    d = WORK / work
    if not d.is_dir():
        raise ValueError("unknown video")
    return d


def path(work: str, name: str) -> Path:
    return wd_of(work) / f"{name}.notes.json"


def _stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError("unknown step")
    return stage


def _empty() -> dict:
    return {"cut": [], "preview": [], "versions": {"cut": [], "preview": []}}


def _from_watch(work: str, name: str) -> list:
    """The old Build & review notes, as preview notes: read once, when this store is first created."""
    p = wd_of(work) / f"{name}.watchnotes.json"
    try:
        old = json.loads(p.read_text(encoding="utf-8-sig")).get("notes", [])
    except (OSError, ValueError):
        return []
    return [{"id": i, "t": n.get("t", 0), "t_end": None, "text": n.get("text", ""), "clip": None, "kind": "note",
             "status": "done" if n.get("status") == "done" else "open", "applied_in": None}
            for i, n in enumerate(old, start=1)]


def load(work: str, name: str) -> dict:
    p = path(work, name)
    if not p.exists():
        j = _empty()
        j["preview"] = _from_watch(work, name)
        return j
    try:
        j = json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError:
        j = _empty()
    base = _empty()
    base.update(j)
    for s in STAGES:
        base["versions"].setdefault(s, [])
        base.setdefault(s, [])
    return base


def save(work: str, name: str, j: dict):
    projectstore.write_json(path(work, name), j)


def notes(work: str, name: str, stage: str) -> list:
    return load(work, name)[_stage(stage)]


def open_notes(work: str, name: str, stage: str) -> list:
    return [n for n in notes(work, name, stage) if n.get("status") != "done"]


def add(work: str, name: str, stage: str, text: str, t: float, t_end: float | None = None, clip=None, kind: str = "note") -> dict:
    text = " ".join(str(text or "").split())
    if len(text) < 2:
        raise ValueError("write the note first")
    with _lock:
        j = load(work, name)
        lst = j[_stage(stage)]
        note = {"id": 1 + max([n["id"] for n in lst] + [0]), "t": round(max(0.0, float(t)), 1),
                "t_end": None if t_end is None else round(float(t_end), 1), "text": text[:800], "clip": clip, "kind": kind,
                "status": "open", "applied_in": None}
        lst.append(note)
        save(work, name, j)
    return note


def edit(work: str, name: str, stage: str, nid: int, text: str) -> None:
    text = " ".join(str(text or "").split())
    if len(text) < 2:
        raise ValueError("write the note first")
    with _lock:
        j = load(work, name)
        for n in j[_stage(stage)]:
            if n["id"] == nid:
                n["text"] = text[:800]
        save(work, name, j)


def delete(work: str, name: str, stage: str, nid: int) -> None:
    with _lock:
        j = load(work, name)
        j[_stage(stage)] = [n for n in j[_stage(stage)] if n["id"] != nid]
        save(work, name, j)


def versions(work: str, name: str, stage: str) -> list:
    return load(work, name)["versions"][_stage(stage)]


def keep_file(work: str, name: str, stage: str, n: int, src: Path) -> str:
    """Keep a version's video under its own name: stitching deletes the older previews, a hard link costs no space (a copy where links fail)."""
    dst = wd_of(work) / f"{name}.{stage}-v{n}.mp4"
    if not dst.exists():
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
    return dst.name


def add_version(work: str, name: str, stage: str, src: Path, changes: list, clips: list, applied_ids: list | None = None) -> dict:
    """Record the video at `src` as the next version; the notes in applied_ids become 'done in <this version>'."""
    wd = wd_of(work)
    with _lock:
        j = load(work, name)
        n = 1 + max([v["n"] for v in j["versions"][_stage(stage)]] + [0])
        v = {"n": n, "file": keep_file(work, name, stage, n, src), "made": time.strftime("%Y-%m-%dT%H:%M:%S"), "changes": list(changes),
             "clips": clips, "marker": f"{stage}{n}"}
        j["versions"][stage].append(v)
        for note in j[stage]:
            if note["id"] in (applied_ids or []):
                note["status"], note["applied_in"] = "done", n
        save(work, name, j)
    projectstore.mark(wd, name, v["marker"])
    return v


def label(stage: str, n: int) -> str:
    return f"{LABEL[stage]} {n}"
