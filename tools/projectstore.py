"""Per-video project history: what changed, when, who changed it, and undo (ADR 0005).

A video's PLAN files are the ones the host and Claude edit (script, clips, beat map, graphics plan, notes, marks, ...; see PLAN_SUFFIXES).
Everything else in the work folder is generated and can be rebuilt, so it is not versioned.

  <work>/.history/journal.jsonl   one line per change: {id, t, ts, file, who, why, sha, size, summary}
  <work>/.history/<sha><ext>      the content of that version (identical content is stored once)
  <work>/<name>.project.json      {"schema": 1, "markers": {"build": {t, files: {file: sha}}, "final": {...}}}

Tools write plan files through write_json / write_text (atomic, then recorded). A file changed some other way (Claude's Edit tool,
a text editor) is noticed by scan() and recorded with who = OUTSIDE. Python stdlib only.
"""
import difflib
import hashlib
import json
import os
import threading
import time
from pathlib import Path

PLAN_SUFFIXES = (".script.md", ".clips.json", ".beatmap.json", ".graphicsplan.json", ".graphicsreview.json",
                 ".storyboard.marks.json", ".sectionnotes.json", ".watchnotes.json", ".shootplan.json",
                 ".shootplan.marks.json", ".footage.json", ".trims.json", ".voiceovers.json", ".selfreview.marks.json",
                 ".workflow.json", ".notes.json", ".teaching.json", ".publish.json", ".shots.json", ".coldopen.json", ".cutreview.json", ".takes.json", ".tags.json", ".locks.json", ".shorts.json", ".story.json", ".moments.json")
HISTORY = ".history"
OUTSIDE = "outside the app"
AUTO = "auto"                                         # files the app creates by itself (empty plans): not counted as changes
actor = os.environ.get("WOOTS_ACTOR", "tool")        # who the next writes are credited to; the server sets this to "user"
_lock = threading.Lock()
_seq = 0


def is_plan(path) -> bool:
    return Path(path).name.endswith(PLAN_SUFFIXES)


# ----------------------------------------------------------------------------- atomic writes
def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def atomic_write(p: Path, data: bytes):
    global _seq
    with _lock:
        _seq += 1
        n = _seq
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{n}.tmp")
    tmp.write_bytes(data)
    _replace(tmp, p)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


# ----------------------------------------------------------------------------- journal
def _dir(wd: Path) -> Path:
    return Path(wd) / HISTORY


def _entries(wd: Path) -> list[dict]:
    p = _dir(wd) / "journal.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue                                         # a half-written last line: skip it
    return out


def _last(wd: Path, file: str):
    return next((e for e in reversed(_entries(wd)) if e["file"] == file and not e.get("gone")), None)


def record(path, who: str | None = None, why: str = ""):
    """Note the current content of a plan file. Returns the journal entry, or None if it is not a plan file or nothing changed."""
    p = Path(path)
    if not is_plan(p) or not p.is_file():
        return None
    b = p.read_bytes()
    sha = _sha(b)
    with _lock:
        last = _last(p.parent, p.name)
        if last and last["sha"] == sha:
            return None
        d = _dir(p.parent)
        d.mkdir(exist_ok=True)
        snap = d / f"{sha}{p.suffix}"
        if not snap.exists():
            snap.write_bytes(b)
        prev = (d / f"{last['sha']}{p.suffix}").read_bytes() if last and (d / f"{last['sha']}{p.suffix}").exists() else None
        if not last and who == OUTSIDE:
            who, why = "before history", "already there when history started"
        ts = time.time()
        e = {"id": time.strftime("%Y%m%dT%H%M%S", time.localtime(ts)) + f"{int(ts * 1000) % 1000:03d}",
             "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)), "ts": round(ts, 3), "file": p.name,
             "who": who or actor, "why": why, "sha": sha, "size": len(b), "summary": summarize(prev, b, p.name)}
        with open(d / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e


def write_json(path, data, who: str | None = None, why: str = ""):
    p = Path(path)
    record(p, OUTSIDE)                                       # the file as it is now, so the first change through the app can be undone too
    atomic_write(p, json.dumps(data, indent=1, ensure_ascii=False).encode("utf-8"))
    record(p, who, why)


def write_text(path, text: str, who: str | None = None, why: str = ""):
    p = Path(path)
    record(p, OUTSIDE)
    atomic_write(p, text.encode("utf-8"))
    record(p, who, why)


def scan(wd) -> list[dict]:
    """Record plan files that changed without going through write_json / write_text (Claude's Edit tool, a text editor)."""
    wd = Path(wd)
    found = []
    for p in sorted(wd.iterdir()) if wd.is_dir() else []:
        if p.is_file() and is_plan(p):
            e = record(p, OUTSIDE, "changed outside the app")
            if e:
                found.append(e)
    return found


# ----------------------------------------------------------------------------- reading history
def history(wd, file: str | None = None, limit: int = 60) -> list[dict]:
    """Newest first. A file seen for the first time shows as 'first version'."""
    wd = Path(wd)
    scan(wd)
    es = [e for e in _entries(wd) if file is None or e["file"] == file]
    return list(reversed(es))[:limit]


def version_bytes(wd, entry_id: str) -> tuple[dict, bytes]:
    e = next((x for x in _entries(Path(wd)) if x["id"] == entry_id), None)
    if not e:
        raise ValueError(f"no version {entry_id!r}")
    snap = _dir(Path(wd)) / f"{e['sha']}{Path(e['file']).suffix}"
    if not snap.exists():
        raise ValueError("that version's copy is missing")
    return e, snap.read_bytes()


def restore(wd, entry_id: str, who: str | None = None) -> dict:
    """Put a file back as it was in that version. The restore is itself a version, so it can be undone too."""
    wd = Path(wd)
    e, b = version_bytes(wd, entry_id)
    atomic_write(wd / e["file"], b)
    new = record(wd / e["file"], who, f"restored the version from {e['t']}")
    return new or e


# ----------------------------------------------------------------------------- diffs
def _items(x):
    """{id: value} for a list of dicts that carry an id, or a dict whose values are all dicts; else None."""
    if isinstance(x, list) and x and all(isinstance(i, dict) for i in x):
        for k in ("id", "beat", "sid"):
            if all(k in i for i in x):
                return {str(i[k]): i for i in x}
    if isinstance(x, dict) and x and all(isinstance(v, dict) for v in x.values()):
        return {str(k): v for k, v in x.items()}
    return None


def structural_diff(a, b) -> dict:
    """{'changed': [ids], 'added': [ids], 'removed': [ids], 'fields': [top-level keys that are not id-lists and differ]}."""
    out = {"changed": [], "added": [], "removed": [], "fields": []}
    if not isinstance(a, dict) or not isinstance(b, dict):
        ia, ib = _items(a), _items(b)
        if ia is not None and ib is not None:
            _merge(out, ia, ib)
        elif a != b:
            out["fields"].append("(whole file)")
        return out
    for k in sorted(set(a) | set(b)):
        if a.get(k) == b.get(k):
            continue
        ia, ib = _items(a.get(k)), _items(b.get(k))
        if ia is not None and ib is not None:
            _merge(out, ia, ib)
        elif ia is not None and k not in b:
            _merge(out, ia, {})
        elif ib is not None and k not in a:
            _merge(out, {}, ib)
        else:
            out["fields"].append(k)
    return out


def _merge(out, ia, ib):
    out["changed"] += [i for i in ib if i in ia and ia[i] != ib[i]]
    out["added"] += [i for i in ib if i not in ia]
    out["removed"] += [i for i in ia if i not in ib]


def summarize(prev: bytes | None, new: bytes, name: str) -> str:
    if prev is None:
        return "first version"
    if name.endswith(".json"):
        try:
            d = structural_diff(json.loads(prev.decode("utf-8-sig")), json.loads(new.decode("utf-8-sig")))
        except ValueError:
            return "edited"
        bits = []
        for key, word in (("changed", "changed"), ("added", "added"), ("removed", "removed")):
            if d[key]:
                ids = ", ".join(d[key][:4]) + (f" +{len(d[key]) - 4} more" if len(d[key]) > 4 else "")
                bits.append(f"{word} {ids}")
        if d["fields"]:
            bits.append("settings: " + ", ".join(d["fields"][:4]))
        return "; ".join(bits) or "edited"
    a, b = prev.decode("utf-8", "replace").splitlines(), new.decode("utf-8", "replace").splitlines()
    plus = minus = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            minus += i2 - i1
        if tag in ("replace", "insert"):
            plus += j2 - j1
    return f"{plus} line{'s' if plus != 1 else ''} added, {minus} removed" if plus or minus else "edited"


def diff(wd, entry_id: str, other_id: str | None = None) -> dict:
    """What differs between a version and another one (default: the file as it is now)."""
    wd = Path(wd)
    e, a = version_bytes(wd, entry_id)
    if other_id:
        o, b = version_bytes(wd, other_id)
    else:
        o, b = None, (wd / e["file"]).read_bytes() if (wd / e["file"]).exists() else b""
    out = {"file": e["file"], "from": e["id"], "to": o["id"] if o else "now"}
    if e["file"].endswith(".json"):
        try:
            out.update(structural_diff(json.loads(a.decode("utf-8-sig")), json.loads(b.decode("utf-8-sig"))))
            return out
        except ValueError:
            pass
    out["text"] = "\n".join(difflib.unified_diff(a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines(),
                                                 "then", "now", lineterm="", n=1))
    return out


# ----------------------------------------------------------------------------- markers: "the plan as of the last build / final render"
def manifest_path(wd, name: str) -> Path:
    return Path(wd) / f"{name}.project.json"


def _manifest(wd, name: str) -> dict:
    try:
        m = json.loads(manifest_path(wd, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    m.setdefault("schema", 1)
    m.setdefault("markers", {})
    return m


def _plan_shas(wd) -> dict:
    wd = Path(wd)
    return {p.name: _sha(p.read_bytes()) for p in sorted(wd.iterdir()) if p.is_file() and is_plan(p)} if wd.is_dir() else {}


def mark(wd, name: str, marker: str):
    """Remember the plan as it is now (call when a build starts, a preview is stitched, the final render starts)."""
    scan(wd)
    m = _manifest(wd, name)
    m["markers"][marker] = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "ts": round(time.time(), 3), "files": _plan_shas(wd)}
    atomic_write(manifest_path(wd, name), json.dumps(m, indent=1).encode("utf-8"))


def changes_since(wd, name: str, marker: str) -> dict | None:
    """Plan files that differ from the marker, or None if that marker was never set."""
    wd = Path(wd)
    scan(wd)
    mk = _manifest(wd, name)["markers"].get(marker)
    if not mk:
        return None
    now, then = _plan_shas(wd), mk["files"]
    auto = {f for f in now if (e := [x for x in _entries(wd) if x["file"] == f and x["ts"] >= mk.get("ts", 0)]) and all(x["who"] == "auto" for x in e)}
    return {"since": mk["t"], "changed": sorted(f for f in now if f in then and now[f] != then[f] and f not in auto),
            "added": sorted(f for f in now if f not in then and f not in auto), "removed": sorted(f for f in then if f not in now)}
