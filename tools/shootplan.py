"""Shoot plan: the stage between the script and the filming (industry name: shot list + B-roll list + pickups).

Claude writes `<name>.shootplan.json` from the script. The host ticks shots off while filming; his ticks live in a separate file so
Claude can rewrite the plan without losing them.

<name>.shootplan.json   (Claude writes it)
  {"version": 1, "script_sig": "<hash of the script's spoken lines>", "notes": "...",
   "shots": [{"id": "SH01", "lines": ["S01", "S02"], "kind": "a_roll|b_roll|screen|vo",
              "what": "what the shot shows", "how": "angle, distance, light, lens, frame rate, anything to remember",
              "fps": 60, "must": true,
              "suggest": ["B Roll/Mech V 2/Failure.MP4"]}]}      # clips Claude thinks already cover it (the host confirms)
  kinds: a_roll = a recording session of the host saying the lines (optional "on_camera": the lines where he is on screen, the rest
         are voice-over); b_roll = a shot of the work; screen = screen recording (Onshape, slicer, a web page);
         reuse = no new filming: built from other shots (e.g. the montage in the hook)
  Every line needs a voice recording (an a_roll shot) AND a picture (a b_roll / screen / reuse shot, or an on_camera line).

<name>.shootplan.marks.json   (the app writes it)
  {"shots": {"SH01": {"status": "todo|shot|have|skip", "note": "", "files": ["rel/path.mp4"]}},
   "pickups": [{"id": "P01", "what": "...", "lines": ["S23"], "status": "todo|shot"}]}

Pure Python, no heavy imports; the review app and the Workflow tab both use it.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(os.path.abspath(__file__)).parent
EDITOR = TOOLS.parent
import config
WORK = config.WORK
ROOT = config.DATA_ROOT                            # the footage share (default <workspace>)
sys.path.insert(0, str(TOOLS))
import clipmap  # noqa: E402  (parse_script)
import footage_cfg  # noqa: E402

KINDS = ("a_roll", "b_roll", "screen", "reuse")
STATUSES = ("todo", "shot", "have", "skip")
SKIP_DIRS = {"_editor", "$recycle.bin", "system volume information", "node_modules"}
SCAN_MAX = 600


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


def plan_path(work, name) -> Path:
    return wd_of(work) / f"{name}.shootplan.json"


def marks_path(work, name) -> Path:
    return wd_of(work) / f"{name}.shootplan.marks.json"


def script_lines(work, name) -> list[dict]:
    p = wd_of(work) / f"{name}.script.md"
    return clipmap.parse_script(p.read_text(encoding="utf-8-sig")) if p.exists() else []


def script_sig(lines: list[dict]) -> str:
    return hashlib.sha256("\n".join(f"{l['id']} {l['said']}" for l in lines).encode()).hexdigest()[:12]


# ----------------------------------------------------------------------------- footage folder
def footage_folder(work, name) -> tuple[Path | None, str | None]:
    """(folder, how): the folder in footage.json, else the project folder that matches the video's title, else None."""
    wd = wd_of(work)
    cfg = read_json(wd / f"{name}.footage.json", {}) or {}
    if cfg.get("folder") and Path(cfg["folder"]).is_dir():
        return Path(cfg["folder"]), "chosen"
    title = (read_json(wd / f"{name}.workflow.json", {}) or {}).get("title") or ""
    for cand in {title, title.replace(":", " -"), title.replace(":", ""), re.sub(r'[<>:"/\\|?*]', " -", title)}:
        if cand and (ROOT / cand).is_dir():
            return ROOT / cand, "guessed"
    return None, None


def scan(folder: Path) -> list[dict]:
    found, base = [], len(folder.parts)
    for root, dirs, files in os.walk(folder):
        rp = Path(root)
        dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in SKIP_DIRS]
        if len(rp.parts) - base >= 4:
            dirs[:] = []
        for f in files:
            if Path(f).suffix.lower() in footage_cfg.VIDEO_EXT and not f.lower().endswith(".proxy.mp4"):
                p = rp / f
                found.append({"rel": p.relative_to(folder).as_posix(), "name": f, "mb": round(p.stat().st_size / 1e6, 1),
                              "role": footage_cfg.auto_role(p.relative_to(folder).as_posix())})
        if len(found) >= SCAN_MAX:
            break
    return sorted(found, key=lambda c: c["rel"].lower())[:SCAN_MAX]


# ----------------------------------------------------------------------------- state
def _shot_status(shot: dict, mark: dict) -> str:
    return mark.get("status") if mark.get("status") in STATUSES else "todo"


def state(work: str, name: str) -> dict:
    wd = wd_of(work)
    lines = script_lines(work, name)
    plan = read_json(plan_path(work, name), None)
    marks = read_json(marks_path(work, name), {}) or {}
    folder, how = footage_folder(work, name)
    clips = scan(folder) if folder else []
    have_files = {c["rel"] for c in clips}
    out = {"work": work, "name": name, "exists": plan is not None, "folder": str(folder) if folder else None,
           "folder_how": how, "clips": clips, "lines": [{"id": l["id"], "said": l["said"], "heading": l["heading"],
                      "text": l["text"][:400], "open": bool(re.search(r"\[(FILL|CONFIRM)", l["text"]))} for l in lines],
           "shots": [], "pickups": marks.get("pickups", []), "notes": (plan or {}).get("notes", ""),
           "warnings": [], "counts": {}, "uncovered": [], "stale": False}
    if not lines:
        out["warnings"].append("there is no script yet (the shoot plan is written from the script)")
    if plan is None:
        return out
    ids = {l["id"] for l in lines}
    covered = set()
    seen_ids = set()
    for s in plan.get("shots", []):
        m = (marks.get("shots") or {}).get(s["id"], {})
        files = [f for f in m.get("files", [])]
        row = {**s, "status": _shot_status(s, m), "note": m.get("note", ""), "files": files,
               "missing_files": [f for f in files if folder and f not in have_files],
               "suggest": [f for f in s.get("suggest", []) if f not in files and (not folder or f in have_files)],
               "bad_lines": [i for i in s.get("lines", []) if i not in ids]}
        if row["kind"] not in KINDS:
            row["kind"] = "b_roll"
        out["shots"].append(row)
        seen_ids.add(s["id"])
        covered.update(i for i in s.get("lines", []) if i in ids)
    for p in out["pickups"]:
        covered.update(i for i in p.get("lines", []) if i in ids)
    voiced, pictured = set(), set()
    for s in plan.get("shots", []):
        sl = [i for i in s.get("lines", []) if i in ids]
        if s.get("kind") == "a_roll":
            voiced.update(sl)
            pictured.update(i for i in s.get("on_camera", []) if i in ids)
        else:
            pictured.update(sl)
    out["uncovered"] = [{"id": l["id"], "said": l["said"], "heading": l["heading"], "no_voice": l["id"] not in voiced,
                         "no_picture": l["id"] not in pictured} for l in lines if l["id"] not in voiced or l["id"] not in pictured]
    out["stale"] = plan.get("script_sig") not in (None, script_sig(lines))
    shots = out["shots"]
    _derive(work, name, shots, ids)
    done = lambda r: r["status"] in ("shot", "have", "skip")
    must = [r for r in shots if r.get("must", True) and r["status"] != "skip" and r["kind"] != "reuse"]
    out["counts"] = {"shots": sum(1 for r in shots if r["kind"] != "reuse"), "done": sum(1 for r in shots if done(r) and r["kind"] != "reuse"), "must": len(must),
                     "must_done": sum(1 for r in must if r["status"] in ("shot", "have")),
                     "a_roll": sum(1 for r in shots if r["kind"] == "a_roll"),
                     "a_roll_done": sum(1 for r in shots if r["kind"] == "a_roll" and r["status"] in ("shot", "have")),
                     "pickups": len(out["pickups"]), "pickups_open": sum(1 for p in out["pickups"] if p.get("status") != "shot")}
    if out["stale"]:
        out["warnings"].append("the script changed after this plan was written: ask Claude to update the plan")
    if out["uncovered"]:
        nv = [u["id"] for u in out["uncovered"] if u["no_voice"]]
        npic = [u["id"] for u in out["uncovered"] if u["no_picture"]]
        if nv:
            out["warnings"].append(f"{len(nv)} script line(s) are in no recording session: " + ", ".join(nv[:8]) + ("..." if len(nv) > 8 else ""))
        if npic:
            out["warnings"].append(f"{len(npic)} script line(s) have no picture planned: " + ", ".join(npic[:8]) + ("..." if len(npic) > 8 else ""))
    bad = [r["id"] for r in shots if r["bad_lines"]]
    if bad:
        out["warnings"].append(f"{', '.join(bad)} point at script lines that no longer exist")
    gone = [r["id"] for r in shots if r["missing_files"]]
    if gone:
        out["warnings"].append(f"{', '.join(gone)}: a clip you attached is no longer in the footage folder")
    if not folder:
        out["warnings"].append("no footage folder chosen yet, so existing clips can't be matched to shots")
    return out


def _derive(work, name, shots, ids):
    """What the rest of the app already knows: a recording session (A-roll) is in hand when every line it covers has a take in the clips tab,
    the voice-over session when every voice-over card is marked recorded. Then every shot gets a 'group' for the tab: shoot, confirm, editor, done, skip."""
    have = set()
    try:
        cj = read_json(wd_of(work) / f"{name}.clips.json", None) or {}
        for cl in cj.get("clips", []):
            for sp in cl.get("spans", []):
                have.update(sp.get("script_lines") or ([sp["line"]] if sp.get("line") else []))
    except (OSError, ValueError):
        pass
    vos = []
    try:
        import scriptedit
        vos = scriptedit.state(work, name).get("voiceovers", [])
    except Exception:                                  # noqa: BLE001 - the voice-over check is a convenience
        pass
    for r in shots:
        if r["kind"] == "a_roll":
            lines = [i for i in r.get("lines", []) if i in ids]
            if lines:
                r["takes_missing"] = [i for i in lines if i not in have]
                r["takes_total"] = len(lines)
                if r["status"] == "todo" and not r["takes_missing"]:
                    r["status"], r["auto"] = "have", "every line has a take in the Clips tab"
            elif vos and "voice" in (r.get("what", "").lower()):
                r["takes_total"] = len(vos)
                r["takes_missing"] = [v["id"] for v in vos if v.get("status") != "recorded"]
                if r["status"] == "todo" and not r["takes_missing"]:
                    r["status"], r["auto"] = "have", "every voice-over card is marked recorded"
        if r["status"] == "skip":
            r["group"] = "skip"
        elif r["status"] in ("shot", "have"):
            r["group"] = "done"
        elif r["kind"] == "reuse":
            r["group"] = "editor"
        elif r["suggest"] or r["files"]:
            r["group"] = "confirm"
        else:
            r["group"] = "shoot"


def _marks_edit(work, name, fn):
    p = marks_path(work, name)
    m = read_json(p, {}) or {}
    m.setdefault("shots", {})
    m.setdefault("pickups", [])
    fn(m)
    write_json(p, m)
    return state(work, name)


def _shot_ids(work, name) -> set:
    plan = read_json(plan_path(work, name), None) or {}
    return {s["id"] for s in plan.get("shots", [])}


def apply_op(work: str, name: str, op: str, b: dict) -> dict:
    sid = b.get("shot")
    if op in ("mark", "attach", "detach", "accept") and sid not in _shot_ids(work, name):
        raise ValueError(f"unknown shot {sid!r}")
    if op == "mark":
        status = b.get("status")
        if status not in STATUSES:
            raise ValueError("status must be one of: " + ", ".join(STATUSES))

        def f(m):
            rec = m["shots"].setdefault(sid, {})
            rec["status"] = status
            if "note" in b:
                rec["note"] = str(b["note"])[:500]
        return _marks_edit(work, name, f)
    if op in ("attach", "accept"):
        rel = b.get("file", "")
        folder, _ = footage_folder(work, name)
        if not folder or not (folder / rel).is_file():
            raise ValueError("that clip is not in the footage folder")

        def f(m):
            rec = m["shots"].setdefault(sid, {})
            files = rec.setdefault("files", [])
            if rel not in files:
                files.append(rel)
            if rec.get("status") in (None, "todo"):
                rec["status"] = "have"
        return _marks_edit(work, name, f)
    if op == "detach":
        def f(m):
            rec = m["shots"].setdefault(sid, {})
            rec["files"] = [x for x in rec.get("files", []) if x != b.get("file")]
            if not rec["files"] and rec.get("status") == "have":
                rec["status"] = "todo"
        return _marks_edit(work, name, f)
    if op == "pickup_add":
        what = (b.get("what") or "").strip()
        if len(what) < 3:
            raise ValueError("say what the shot is")

        def f(m):
            n = 1 + max([int(re.sub(r"\D", "", p["id"]) or 0) for p in m["pickups"]] + [0])
            m["pickups"].append({"id": f"P{n:02d}", "what": what[:300], "lines": [x for x in (b.get("lines") or []) if isinstance(x, str)][:6],
                                 "status": "todo"})
        return _marks_edit(work, name, f)
    if op == "pickup_mark":
        def f(m):
            for p in m["pickups"]:
                if p["id"] == b.get("id"):
                    p["status"] = "shot" if b.get("status") == "shot" else "todo"
        return _marks_edit(work, name, f)
    if op == "pickup_del":
        def f(m):
            m["pickups"] = [p for p in m["pickups"] if p["id"] != b.get("id")]
        return _marks_edit(work, name, f)
    raise ValueError(f"unknown operation {op!r}")


def checklist(work: str, name: str) -> str:
    """A plain-text list for the phone or the bench: what is still to shoot, grouped by script section."""
    s = state(work, name)
    out, last = [], object()
    for r in s["shots"]:
        if r["status"] != "todo":
            continue
        head = next((l["heading"] for l in s["lines"] if l["id"] in r.get("lines", [])), None)
        if head != last:
            out.append(f"\n{head or 'Other'}")
            last = head
        fps = f" [{r['fps']} fps]" if r.get("fps") else ""
        out.append(f"[ ] {r['id']} ({', '.join(r.get('lines', []))}) {r['kind'].replace('_', '-')}: {r['what']}{fps}")
        if r.get("how"):
            out.append(f"      {r['how']}")
    for p in s["pickups"]:
        if p.get("status") != "shot":
            out.append(f"[ ] {p['id']} pickup: {p['what']}")
    return "\n".join(out).strip() or "Nothing left to shoot."


if __name__ == "__main__":
    print(json.dumps(state(sys.argv[1], sys.argv[2]), indent=1)[:4000])
