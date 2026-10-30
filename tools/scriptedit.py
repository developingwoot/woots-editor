"""Script tab, step 1: read and edit `<name>.script.md` without Claude (no tokens), with a saved version for every change.

The script file stays the way Claude writes it:
    ## SECTION NAME (0:00 - 0:45)            a heading
    [VISUAL: ...]                             what is on screen: belongs to the NEXT spoken line
    S01 The spoken line.                      a spoken line; the id (S01, S02...) is stable, later stages refer to it
    [NOTE: ...]                               a note: belongs to the PREVIOUS spoken line
Markers inside a line: `[FILL: ...]` = a fact only the host has, `[CONFIRM: ...]` = a claim to check. The tab turns them into answer boxes;
answering replaces the marker with the host's words (FILL) or removes it (CONFIRM).

Every write first saves the file to `<name>.script.history\\<time>-<what>.md` (newest 200 kept), so any change can be undone.
Pure Python: the review app and the Workflow tab both use it.
"""
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
EDITOR = TOOLS.parent
import config
import projectstore
WORK = config.WORK
ID_RE = re.compile(r"^(\W*)(S\d{2,3})\b([\s:.\-–—]*)(.*)$")
META_KEYS = ("Logline", "Thesis", "Promise")
META_RE = re.compile(r"^(Logline|Thesis|Promise)\b([^:]*):\s*(.*)$")        # header lines above the first ## heading
VO_NOTE_RE = re.compile(r"^\[NOTE:\s*(TP\d{2})\s*\|\s*(.*)\]\s*$")      # the teaching-point voice-over notes: [NOTE: TP01 | line S08 | term: ... | VO (the creator): "..." | ...]
MARK_RE = re.compile(r"\[(FILL|CONFIRM)[^\]]*\]")
BRACKET_RE = re.compile(r"\[[^\]]*\]")
WPM = 170.0                                   # speaking pace used for the time estimate
KEEP = 200


def _replace(tmp, p):
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def wd_of(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work:
        raise ValueError(f"bad name {work!r}")
    d = WORK / work
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def script_path(work, name) -> Path:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"bad name {name!r}")
    return wd_of(work) / f"{name}.script.md"


def history_dir(work, name) -> Path:
    return wd_of(work) / f"{name}.script.history"


def _read_lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8-sig").splitlines()


def _kind(raw: str) -> str:
    s = raw.strip()
    if s.startswith("##"):
        return "heading"
    if s.startswith("# "):
        return "title"
    if ID_RE.match(raw):
        return "line"
    if s.startswith("[VISUAL"):
        return "visual"
    if s.startswith("[NOTE"):
        return "note"
    return "other"


def _markers(text: str) -> list[dict]:
    return [{"k": i, "kind": m.group(1), "text": m.group(0)} for i, m in enumerate(MARK_RE.finditer(text))]


def _said(body: str) -> str:
    return BRACKET_RE.sub(" ", body).strip()


def vo_status_path(work, name) -> Path:
    return wd_of(work) / f"{name}.voiceovers.json"


def _vo_read(work, name) -> dict:
    import json
    p = vo_status_path(work, name)
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _vo_fields(raw: str):
    """A voice-over note -> {id, line, term, text, why, graphic, secs, cut_if}, or None when the note is not one."""
    m = VO_NOTE_RE.match(raw.strip())
    if not m:
        return None
    out = {"id": m.group(1), "line": "", "term": "", "text": "", "why": "", "graphic": "", "secs": "", "cut_if": ""}
    for part in m.group(2).split(" | "):
        p = part.strip()
        low = p.lower()
        if low.startswith("line "):
            out["line"] = p[5:].strip()
        elif low.startswith("term:"):
            out["term"] = p[5:].strip().strip('"')
        elif low.startswith("vo"):
            q = re.search(r':\s*"(.*)"\s*$', p)
            out["text"] = q.group(1) if q else p.split(":", 1)[-1].strip()
        elif low.startswith("why it matters:"):
            out["why"] = p.split(":", 1)[1].strip()
        elif low.startswith("graphic:"):
            out["graphic"] = p.split(":", 1)[1].strip()
        elif re.match(r"^\d+(-\d+)?\s*s$", p):
            out["secs"] = p
        elif low.startswith("cut if:"):
            out["cut_if"] = re.split(r"\bVERIFY\b", p.split(":", 1)[1])[0].strip()
    return out


def state(work: str, name: str) -> dict:
    p = script_path(work, name)
    out = {"work": work, "name": name, "exists": p.exists(), "title": None, "header": [], "sections": [], "history": history(work, name),
           "stats": {}, "meta": {}, "voiceovers": []}
    vo_marks = _vo_read(work, name)
    if not p.exists():
        return out
    lines = _read_lines(p)
    sec, pend_visual = None, []
    for i, raw in enumerate(lines):
        k = _kind(raw)
        if k == "title":
            out["title"] = raw.lstrip("# ").strip()
            continue
        if k == "heading":
            sec = {"heading": raw.lstrip("# ").strip(), "row": i, "rows": [], "has_lines": False, "words": 0, "est_s": 0.0}
            out["sections"].append(sec)
            pend_visual = []
            continue
        if sec is None:
            mm = META_RE.match(raw)
            if mm:
                out["meta"][mm.group(1)] = {"text": mm.group(3).strip(), "draft": "draft" in mm.group(2).lower(), "row": i}
            elif raw.strip() and raw.strip() != "---":
                out["header"].append(raw)
            continue
        row = {"i": i, "kind": k, "text": raw}
        if k == "line":
            m = ID_RE.match(raw)
            row.update(id=m.group(2), body=m.group(4), markers=_markers(m.group(4)), visuals=pend_visual, notes=[])
            w = len(_said(m.group(4)).split())
            row["words"] = w
            sec["has_lines"] = True
            sec["words"] += w
            pend_visual = []
            sec["rows"].append(row)
        elif k == "visual":
            pend_visual.append({"i": i, "text": raw})
        elif k == "note":
            last = next((r for r in reversed(sec["rows"]) if r["kind"] == "line"), None)
            note = {"i": i, "text": raw, "open": bool(re.search(r"CONFIRM|FILL", raw)), "markers": _markers(raw)}
            vo = _vo_fields(raw)
            if vo:
                note["vo"] = vo["id"]
                mk = vo_marks.get(vo["id"]) or {}
                vo.update(row=i, at=last["id"] if last is not None else vo["line"], status=mk.get("status", "todo"), takes=mk.get("takes", []), pick=mk.get("pick", 0))
                out["voiceovers"].append(vo)
            if last is not None:
                last["notes"].append(note)
            else:
                sec["rows"].append(row)
        elif raw.strip() and raw.strip() != "---":
            sec["rows"].append(row)
    words = 0
    for s in out["sections"]:
        s["est_s"] = round(s["words"] / (WPM / 60.0), 1)
        words += s["words"]
    allrows = [r for s in out["sections"] for r in s["rows"] if r["kind"] == "line"]
    n_mark = sum(len(r["markers"]) for r in allrows) + sum(len(n["markers"]) for r in allrows for n in r["notes"])
    n_notes = sum(1 for r in allrows for n in r["notes"] if n["open"] and not n["markers"])
    out["stats"] = {"lines": len(allrows), "words": words, "est_s": round(words / (WPM / 60.0)), "wpm": WPM,
                    "fills": sum(1 for r in allrows for mk in r["markers"] if mk["kind"] == "FILL")
                    + sum(1 for r in allrows for n in r["notes"] for mk in n["markers"] if mk["kind"] == "FILL"),
                    "confirms": sum(1 for r in allrows for mk in r["markers"] if mk["kind"] == "CONFIRM")
                    + sum(1 for r in allrows for n in r["notes"] for mk in n["markers"] if mk["kind"] == "CONFIRM"),
                    "open_notes": n_notes, "markers": n_mark}
    return out


# ----------------------------------------------------------------------------- versions
def history(work, name) -> list[dict]:
    d = history_dir(work, name)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.md"), reverse=True)[:60]:
        stem = f.stem
        t, _, what = stem.partition("-")
        t2, _, what = what.partition("-")
        out.append({"file": f.name, "t": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t2[:2]}:{t2[2:4]}:{t2[4:6]}", "what": what.replace("_", " "), "size": f.stat().st_size})
    return out


def _save_version(work, name, what: str):
    p = script_path(work, name)
    if not p.exists():
        return
    d = history_dir(work, name)
    d.mkdir(exist_ok=True)
    data = p.read_bytes()
    last = sorted(d.glob("*.md"))[-1:] or []
    if last and last[0].read_bytes() == data:
        return
    tag = re.sub(r"[^A-Za-z0-9 ]+", "", what)[:40].strip().replace(" ", "_") or "change"
    f = d / f"{time.strftime('%Y%m%d')}-{time.strftime('%H%M%S')}-{tag}.md"
    n = 1
    while f.exists():
        n += 1
        f = d / f"{time.strftime('%Y%m%d')}-{time.strftime('%H%M%S')}-{tag}{n}.md"
    f.write_bytes(data)
    for old in sorted(d.glob("*.md"))[:-KEEP]:
        old.unlink()


def _write(work, name, lines: list[str], what: str):
    p = script_path(work, name)
    _save_version(work, name, what)
    projectstore.write_text(p, "\n".join(lines) + "\n", why=what)


# ----------------------------------------------------------------------------- operations
def _row(lines: list[str], i, old: str | None) -> str:
    if not isinstance(i, int) or i < 0 or i >= len(lines):
        raise ValueError("that line is not in the script any more: refresh")
    if old is not None and lines[i] != old:
        raise ValueError("that line changed since you loaded the page: refresh and try again")
    return lines[i]


def _next_id(lines: list[str]) -> str:
    nums = [int(m.group(2)[1:]) for m in (ID_RE.match(l) for l in lines) if m]
    return f"S{(max(nums) if nums else 0) + 1:02d}"


def _attached(lines: list[str], i: int) -> tuple[int, int]:
    """Row range [a, b] of a spoken line with the [VISUAL] rows above it and the [NOTE] rows below it."""
    a = i
    while a - 1 >= 0 and _kind(lines[a - 1]) == "visual":
        a -= 1
    b = i
    while b + 1 < len(lines) and _kind(lines[b + 1]) == "note":
        b += 1
    return a, b


def apply_op(work: str, name: str, op: str, b: dict) -> dict:
    p = script_path(work, name)
    if not p.exists():
        raise ValueError("there is no script yet")
    lines = _read_lines(p)
    if op == "edit":
        i, raw = b.get("row"), _row(lines, b.get("row"), b.get("old"))
        text = " ".join(str(b.get("text", "")).split())
        if not text:
            raise ValueError("the line is empty: use Remove if you want it gone")
        m = ID_RE.match(raw)
        if m:
            lines[i] = f"{m.group(1)}{m.group(2)} {text}"
            _write(work, name, lines, f"edit {m.group(2)}")
        else:
            lines[i] = text
            _write(work, name, lines, "edit a note")
    elif op == "fill":
        i, raw = b.get("row"), _row(lines, b.get("row"), b.get("old"))
        ms = list(MARK_RE.finditer(raw))
        k = b.get("k")
        if not isinstance(k, int) or k < 0 or k >= len(ms):
            raise ValueError("that marker is gone: refresh")
        m = ms[k]
        answer = " ".join(str(b.get("answer", "")).split())
        if not answer and m.group(1) == "FILL":
            raise ValueError("a [FILL] needs your answer (type it in the box)")
        before, after = raw[:m.start()], raw[m.end():]
        if not answer:                                   # confirmed: drop the marker and tidy the spaces around it
            new = (before.rstrip() + " " + after.lstrip()).strip() if before.strip() and after.strip() else (before + after).strip()
        else:
            new = before + answer + after
        lines[i] = new
        idm = ID_RE.match(raw)
        _write(work, name, lines, f"{'answer' if answer else 'confirm'} {idm.group(2) if idm else 'a note'}")
    elif op == "insert":
        i = b.get("after")
        _row(lines, i, None)
        text = " ".join(str(b.get("text", "")).split())
        if not text:
            raise ValueError("write the line first")
        if _kind(lines[i]) == "line":
            i = _attached(lines, i)[1]
        nid = _next_id(lines)
        lines.insert(i + 1, f"{nid} {text}")
        _write(work, name, lines, f"add {nid}")
        return {**state(work, name), "new_id": nid}
    elif op == "delete":
        i, raw = b.get("row"), _row(lines, b.get("row"), b.get("old"))
        m = ID_RE.match(raw)
        if m:
            a, z = _attached(lines, i)
            del lines[a:z + 1]
            _write(work, name, lines, f"remove {m.group(2)}")
        else:
            del lines[i]
            _write(work, name, lines, "remove a note")
    elif op == "meta":
        key = b.get("key")
        text = " ".join(str(b.get("text", "")).split())
        if key not in META_KEYS:
            raise ValueError("key must be one of: " + ", ".join(META_KEYS))
        if not text:
            raise ValueError("write the sentence first")
        first_head = next((n for n, l in enumerate(lines) if _kind(l) == "heading"), len(lines))
        def meta_key(l):
            m = META_RE.match(l)
            return m.group(1) if m else None
        hit = [n for n, l in enumerate(lines[:first_head]) if meta_key(l) == key]
        if hit:
            lines[hit[0]] = f"{key}: {text}"
        else:
            last = max([n for n, l in enumerate(lines[:first_head]) if META_RE.match(l)] or [1])
            lines.insert(last + 1, f"{key}: {text}")
        _write(work, name, lines, f"set the {key.lower()}")
    elif op == "vo_takes":
        import json
        vid = str(b.get("id", ""))
        if not any(_vo_fields(l) and _vo_fields(l)["id"] == vid for l in lines):
            raise ValueError(f"no voice-over {vid!r} in the script")
        takes = []
        for t in b.get("takes") or []:
            f = str(t.get("file", "")).replace("\\", "/")
            if not f or ".." in f.split("/") or not re.search(r"\.(wav|m4a|mp3|aac|flac|mkv|mp4|mov)$", f, re.I):
                raise ValueError("a take needs the audio file's name inside the footage folder")
            a, z = float(t.get("start", 0)), float(t.get("end", 0))
            if not 0 <= a < z:
                raise ValueError("a take needs a start before its end")
            takes.append({"file": f, "start": round(a, 2), "end": round(z, 2), "note": str(t.get("note", ""))[:200]})
        marks = _vo_read(work, name)
        rec = marks.setdefault(vid, {})
        rec.update(takes=takes, pick=max(0, min(int(b.get("pick", 0)), max(len(takes) - 1, 0))), at=time.time())
        if takes:
            rec["status"] = "recorded"
        vp = vo_status_path(work, name)
        tmp = vp.with_name(f"{vp.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(marks, indent=1), encoding="utf-8")
        _replace(tmp, vp)
    elif op == "vo_mark":
        import json
        vid, status = str(b.get("id", "")), b.get("status")
        if status not in ("todo", "recorded"):
            raise ValueError("status must be todo or recorded")
        if not any(_vo_fields(l) and _vo_fields(l)["id"] == vid for l in lines):
            raise ValueError(f"no voice-over {vid!r} in the script")
        marks = _vo_read(work, name)
        marks.setdefault(vid, {}).update(status=status, at=time.time())
        vp = vo_status_path(work, name)
        tmp = vp.with_name(f"{vp.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(marks, indent=1), encoding="utf-8")
        _replace(tmp, vp)
    elif op == "restore":
        f = history_dir(work, name) / os.path.basename(str(b.get("file", "")))
        if not f.is_file():
            raise ValueError("that version is not there any more")
        _save_version(work, name, "before restore")
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_bytes(f.read_bytes())
        _replace(tmp, p)
        projectstore.record(p, why="restored an older version")
    else:
        raise ValueError(f"unknown operation {op!r}")
    return state(work, name)


if __name__ == "__main__":
    import json
    s = state(sys.argv[1], sys.argv[2])
    print(json.dumps(s["stats"]), len(s["sections"]))
