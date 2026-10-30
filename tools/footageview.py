"""The Footage step (ADR 0007): the footage folder, the recordings as a grid, and what we have for each shot of the outline.

Recordings are read from the folder itself (brolllib.clips_of: every video file, any depth). A recording's length is probed once and cached in
`<work>/v2-durations.json` (keyed by size and date) so the screen opens quickly the next time. Nothing here writes a plan file.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import brolllib
import config
import footage_cfg

WORK = config.WORK


def _cfg(work: str, name: str) -> dict:
    return footage_cfg.load(WORK / work / f"{name}.footage.json")


def folder_of(work: str, name: str):
    """(folder, how) - the chosen folder, else the one that matches the video's title."""
    import shootplan
    return shootplan.footage_folder(work, name)


def _durations(work: str, folder: Path, rels: list) -> dict:
    cache_path = WORK / work / "v2-durations.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, todo = {}, []
    for rel in rels:
        try:
            st = (folder / rel).stat()
        except OSError:
            continue
        hit = cache.get(rel)
        if hit and hit[0] == st.st_size and hit[1] == int(st.st_mtime):
            out[rel] = hit[2]
        else:
            todo.append((rel, st))

    def probe(item):
        rel, st = item
        try:
            return rel, st, brolllib.dur_of(str(folder / rel))
        except Exception:                               # noqa: BLE001  (a file ffmpeg cannot read has no length to show)
            return rel, st, None
    if todo:
        with ThreadPoolExecutor(6) as ex:
            for rel, st, d in ex.map(probe, todo):
                out[rel] = d
                cache[rel] = [st.st_size, int(st.st_mtime), d]
        tmp = cache_path.with_suffix(".part")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, cache_path)
    return out


def recordings(work: str, name: str, reading: bool = False) -> dict:
    """{folder, how, total, read, unread, looked, rows: [{ref, len, speech, looked}]}. `ref` is internal (the page sends it back for a picture)."""
    import views
    folder, how = folder_of(work, name)
    out = {"folder": str(folder) if folder else None, "how": how, "total": 0, "read": 0, "unread": 0, "unread_refs": [], "looked": 0, "ignored": 0, "thin": 0, "rows": []}
    if not folder or not Path(folder).is_dir():
        return out
    cfg = footage_cfg.with_titles({**_cfg(work, name), "folder": str(folder)}, work, name)
    rels = brolllib.clips_of(cfg, skip_ignored=False)
    durs = _durations(work, Path(folder), rels)
    vis = brolllib.state(work, name) if (WORK / work / f"{name}.footage.json").exists() else {"missing": rels}
    missing_vision = set(vis.get("missing", rels))
    analysis = cfg.get("analysis") or {}
    import tags
    mine = tags.by_clip(tags.load(work, name))
    try:
        lib = json.loads(brolllib.paths(work, name)[1].read_text(encoding="utf-8")).get("clips", {})
    except (OSError, ValueError):
        lib = {}
    for rel in rels:
        role = footage_cfg.role_of(cfg, rel)[0]
        needs_words = role != "broll"                              # silent footage has nothing to read
        if not needs_words:
            speech = "silent footage"
        elif rel in analysis:
            speech = "read"
        else:
            speech = "reading now" if reading else "not read yet"
        skip = footage_cfg.is_ignored(cfg, rel)
        row = {"ref": rel, "len": views.time_text(durs.get(rel) or 0) if durs.get(rel) else "", "speech": speech, "looked": rel not in missing_vision,
               "ignored": skip, "auto": skip and rel not in (cfg.get("ignore") or []),
               "tags": len(mine.get(rel, [])), "thin": not mine.get(rel) and role in ("broll", "unassigned") and tags.thin(lib.get(rel), durs.get(rel))}
        out["rows"].append(row)
        if skip:                                                   # not material for this video: not counted, not read, not looked at
            out["ignored"] += 1
            continue
        out["read"] += speech == "read"
        out["unread"] += needs_words and rel not in analysis
        if needs_words and rel not in analysis:
            out["unread_refs"].append(rel)
        out["looked"] += row["looked"]
    out["thin"] = sum(1 for r in out["rows"] if r["thin"] and not r["ignored"])
    out["total"] = len(rels) - out["ignored"]
    return out
