"""Plain-language view models for the v2 UI (ADR 0007). The sentences live here, not in JS, so tests can check them."""
import time

# pipeline -> (sentence while running, sentence when done, typical minutes)
_PIPELINES = {
    "analyze": ("Reading your recordings", "Recordings read", 5),
    "clipmap": ("Matching your clips to the outline", "Clips matched", 2),
    "storyboard": ("Drawing the storyboard", "Storyboard drawn", 2),
    "selfreview": ("Checking the preview", "Preview checked", 3),
    "final": ("Rendering the final video", "Final video rendered", 15),
    "cut": ("Making the rough cut", "Rough cut ready", 3),
    "preview": ("Making the preview", "Preview ready", 6),
    "outline": ("Drafting the outline", "Outline ready", 2),
    "archive": ("Saving the project and cleaning up", "Video archived", 3),
    "vision": ("Looking at your footage", "Footage looked at", 20),
    "options": ("Looking for more takes", "More takes found", 2),
    "teaching": ("Looking for teaching moments", "Teaching moments found", 1),
    "moments": ("Looking for fun moments", "Fun moments found", 1),
    "publish": ("Writing the publishing details", "Publishing details ready", 2),
    "shorts": ("Working on your shorts", "Shorts ready", None),
    "score": ("Measuring the final against the reference videos", "Final measured", 3),
}


def minutes_text(minutes) -> str:
    """'about 4 min' / 'less than a minute' / 'about 2 hours'; never decimals."""
    if minutes is None:
        return ""
    if minutes < 1:
        return "less than a minute"
    if minutes < 90:
        return f"about {round(minutes)} min"
    return f"about {round(minutes / 60)} hours"


def time_text(seconds) -> str:
    """0:42 or 1:05:09 from seconds; whole seconds only."""
    s = max(0, int(round(float(seconds or 0))))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def job_sentence(job: dict, now: float | None = None) -> dict:
    """What the job bar shows: one sentence, progress 0..1 (None if unknown), an estimate, and a plain error with the log behind 'Show details'."""
    running, done_text, typical = _PIPELINES.get(job.get("pipeline"), ("Working", "Done", None))
    running, done_text = job.get("sentence") or running, job.get("done_sentence") or done_text         # a job can say what it is doing in its own words
    now = time.time() if now is None else now
    steps = job.get("steps") or []
    if not job.get("done"):
        elapsed = max(0.0, now - job.get("started", now)) / 60
        progress = (job.get("step", 0) / len(steps)) if len(steps) > 1 else None
        left = None if typical is None else max(0.0, typical - elapsed)
        return {"state": "running", "sentence": running, "progress": progress, "estimate": minutes_text(left) if left is not None else "",
                "error": None, "details": job.get("log", "")}
    if job.get("ok"):
        return {"state": "done", "sentence": done_text, "progress": 1.0, "estimate": "", "error": None, "details": job.get("log", "")}
    return {"state": "failed", "sentence": running, "progress": None, "estimate": "",
            "error": f"{running} did not finish. Nothing was changed.", "details": job.get("log", "")}


# ----------------------------------------------------------------------------- home and step bar
STEPS = [("outline", "Outline"), ("footage", "Footage"), ("rough-cut", "Rough cut"), ("preview", "Preview"), ("final", "Final"), ("shorts", "Shorts")]
STEP_IDS = [s for s, _ in STEPS]
_PIPELINE_STEP = {"archive": "final", "vision": "footage", "options": "rough-cut", "teaching": "rough-cut", "moments": "rough-cut", "analyze": "footage", "clipmap": "footage", "cut": "rough-cut", "preview": "preview", "outline": "outline", "final": "final",
                  "publish": "final", "shorts": "shorts", "score": "final"}


def key_of(work: str, name: str) -> str:
    return f"{work}~{name}"


def split_key(key: str) -> tuple[str, str]:
    import config
    work, _, name = str(key).partition("~")
    return config.safe_part(work), config.safe_part(name)


def facts(work: str, name: str) -> dict:
    """What exists for a video, read from files only (no side effects, no renders). Everything step_of needs."""
    import reviewnotes
    import workflow
    wd = workflow.work_dir(work)
    preview = workflow.stage_path(wd, name, next(s for s in workflow.STAGES if s["id"] == "review"))
    has_preview = bool(preview) and preview.exists()
    has_final = has_preview and any(f.stat().st_mtime > preview.stat().st_mtime for f in wd.glob("* v*(1080p).mp4"))
    kept = 0
    try:
        import shortsapp
        kept = sum(1 for s in shortsapp.read_raw(work, name).get("shorts", []) if s.get("status") == "kept")
    except (ValueError, OSError):
        pass
    return {"work": work, "name": name, "title": workflow.load(work, name).get("title") or name,
            "outline": (wd / f"{name}.script.md").exists(), "clips": (wd / f"{name}.clips.json").exists(),
            "cut": (wd / f"{name}.beatmap.json").exists(), "cut_made": bool(reviewnotes.versions(work, name, "cut")), "preview": has_preview, "final": has_final,
            "shorts_kept": kept, "finished": (wd / "FINALIZED.json").exists(), "outline_gaps": _outline_gaps(wd, name)}


def _outline_gaps(wd, name: str) -> int:
    """How many sections of the outline have no shot idea yet (0 when there is no outline)."""
    import outline
    try:
        return outline.gaps(outline.parse((wd / f"{name}.script.md").read_text(encoding="utf-8-sig")))
    except OSError:
        return 0


def _dots(f: dict, current: str) -> list[dict]:
    have = {"outline": f["outline"], "footage": f["clips"], "rough-cut": f.get("cut_made", f["cut"]), "preview": f["preview"], "final": f["final"],
            "shorts": f["shorts_kept"] > 0}
    return [{"id": sid, "title": title, "current": sid == current, "dot": "result" if have[sid] else "none"} for sid, title in STEPS]


def step_of(f: dict, job: dict | None = None) -> dict:
    """The step a video is at, in a sentence, with the one button that goes there. A running job (see job_sentence) takes over the sentence."""
    if f["shorts_kept"]:
        n = f["shorts_kept"]
        step, sentence, button = "shorts", f"Shorts: {n} kept", "Open the shorts"
    elif f["final"]:
        step, sentence, button = "final", "Final rendered: publishing details ready", "Open the final"
    elif f["preview"]:
        step, sentence, button = "preview", "Preview ready to watch", "Watch the preview"
    elif f.get("cut_made", f["cut"]):
        step, sentence, button = "rough-cut", "Rough cut ready to watch", "Watch the rough cut"
    elif f["cut"]:
        step, sentence, button = "rough-cut", "The plan is ready: make the rough cut", "Make the rough cut"
    elif f["clips"]:
        step, sentence, button = "footage", "Footage read: ready to make the rough cut", "Make the rough cut"
    elif f["outline"] and f.get("outline_gaps"):
        n = f["outline_gaps"]
        step, sentence, button = "outline", f"Outline: {n} section{'s' if n != 1 else ''} still need{'' if n != 1 else 's'} shot ideas", "Open the outline"
    elif f["outline"]:
        step, sentence, button = "footage", "Outline written: add your footage next", "Add footage"
    else:
        step, sentence, button = "outline", "Outline: not started", "Start the outline"
    if job and not job.get("done"):
        j = job_sentence(job)
        step = _PIPELINE_STEP.get(job.get("pipeline"), step)
        sentence = f"Claude is working: {j['sentence'].lower()}" + (f" ({j['estimate']})" if j["estimate"] else "")
    return {"step": step, "sentence": sentence, "button": button, "steps": _dots(f, step)}


def _has_thumb(work: str, name: str) -> bool:
    import usage
    try:
        return usage.thumb_path(work, name) is not None
    except Exception:       # noqa: BLE001  (a missing footage folder is not worth an error on the home screen)
        return False


def home(jobs: list[dict] | None = None) -> dict:
    """The video cards for the home screen: {'videos': [...], 'done': [...]}. Each card: key, title, sentence, step, button, thumb."""
    import workflow
    running = next((j for j in reversed(jobs or []) if j.get("pipeline") and not j.get("done")), None)
    active, done = [], []
    for v in workflow.list_videos():
        for name in v["names"]:
            f = facts(v["work"], name)
            s = step_of(f, running if running and (running.get("work"), running.get("name")) == (v["work"], name) else None)
            card = {"key": key_of(v["work"], name), "title": f["title"], "sentence": s["sentence"], "step": s["step"], "button": s["button"],
                    "thumb": _has_thumb(v["work"], name)}
            (done if f["finished"] else active).append(card)
    return {"videos": active, "done": done, "job": job_sentence(running) if running else None}


# ----------------------------------------------------------------------------- the review screen (rough cut and preview)
_STAGE_WORD = {"cut": "cut", "preview": "preview"}


def _frame(src, cache, t: float):
    """A small JPEG of the video `src` at time t, made once into the folder `cache`."""
    import hashlib
    import subprocess
    import storyboard
    if not src.is_file():
        raise ValueError("that video is gone")
    t = max(0.0, round(float(t), 1))
    cache.mkdir(exist_ok=True)
    out = cache / (hashlib.sha1(f"{src.name}|{src.stat().st_size}|{t}".encode()).hexdigest()[:16] + ".jpg")
    if not out.exists():
        r = subprocess.run([storyboard.find_ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t:.1f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=320:-2", "-q:v", "5", "-y", str(out)], capture_output=True, timeout=60)
        if r.returncode != 0 or not out.exists():
            raise ValueError("could not read a picture from the video")
    return out


def frame_path(work: str, file: str, t: float):
    """A small JPEG of a video in the work folder (a version of the cut or preview) at time t."""
    from pathlib import Path
    import workflow
    wd = workflow.work_dir(work)
    return _frame(wd / Path(file).name, wd / "v2-frames", t)


def source_path(work: str, name: str, rel: str):
    """A recording inside the video's footage folder (never outside it)."""
    import os
    from pathlib import Path
    import shootplan
    folder, _ = shootplan.footage_folder(work, name)
    if not folder:
        raise ValueError("the footage folder is not set")
    p = Path(os.path.abspath(Path(folder) / rel))
    if Path(os.path.abspath(folder)) not in p.parents:
        raise ValueError("that file is not in the footage folder")
    return p


def lock_view(work: str, name: str) -> dict:
    """The cut's transcript with the good / don't-touch marks: {sentences: [{id, text, start, end, at, lock}], marks: n}."""
    import beatmap
    import clipmap
    import locks
    data = clipmap.read_json(beatmap.path_of(work, name), None)
    rows = locks.view(work, name, data) if data else []
    for r in rows:
        r["at"] = time_text(r["start"])
    return {"sentences": rows, "marks": len(locks.load(work, name))}


def clip_length(work: str, name: str, rel: str):
    """Seconds in a recording of the footage folder (None if it cannot be measured); refuses a file outside the folder."""
    from pathlib import Path
    import footageview
    import shootplan
    if not source_path(work, name, rel).is_file():
        raise ValueError("that clip was not found in the footage folder")
    return footageview._durations(work, Path(shootplan.footage_folder(work, name)[0]), [rel]).get(rel) or None


def source_frame(work: str, name: str, rel: str, t: float):
    import workflow
    return _frame(source_path(work, name, rel), workflow.work_dir(work) / "v2-frames", t)


def review(work: str, name: str, stage: str, version: int | None = None, running: bool = False) -> dict:
    """Everything the review screen shows: the video to play, the clips as a strip, the notes, the versions and the one button."""
    import reviewnotes
    import makeversion
    from urllib.parse import quote
    word = _STAGE_WORD[stage]
    if stage == "preview":
        makeversion.ensure_baseline(work, name, stage)
    vs = reviewnotes.versions(work, name, stage)
    cur = next((v for v in vs if v["n"] == version), vs[-1] if vs else None)
    key = key_of(work, name)
    notes = reviewnotes.notes(work, name, stage)
    open_n = [n for n in notes if n.get("status") != "done"]
    pending = {n["clip"]: n["kind"] for n in open_n if n.get("choice") is not None and n.get("clip")}
    label = lambda n: reviewnotes.label(stage, n)           # noqa: E731
    out = {"key": key, "stage": stage, "has_video": cur is not None, "version": None, "versions": [], "notes": [], "clips": [], "button": None,
           "teaching": [], "moments": []}
    for v in reversed(vs):
        out["versions"].append({"n": v["n"], "label": label(v["n"]), "changes": v["changes"], "current": bool(cur) and v["n"] == cur["n"],
                                "latest": v["n"] == vs[-1]["n"]})
    if cur:
        out["version"] = {"n": cur["n"], "label": label(cur["n"]), "changes": cur["changes"], "suggestions": cur.get("suggestions", []),
                          "lesson": "" if cur.get("lesson_added") else cur.get("lesson", ""),
                          "video": f"/media/{quote(work)}/{quote(cur['file'])}",
                          "latest": cur["n"] == vs[-1]["n"]}
        total = max([c["start"] + c["dur"] for c in cur["clips"]] + [0.0])
        for c in cur["clips"]:
            mid = c["start"] + c["dur"] / 2
            out["clips"].append({"start": c["start"], "dur": c["dur"], "at": time_text(c["start"]), "share": c["dur"] / total if total else 0,
                                 "ref": c.get("ref"), "pending": pending.get(c.get("ref")),
                                 "frame": f"/api/v2/frame?key={quote(key)}&file={quote(cur['file'])}&t={mid:.1f}"})
    for n in sorted(notes, key=lambda x: x["t"]):
        when = time_text(n["t"]) + (f"–{time_text(n['t_end'])}" if n.get("t_end") is not None else "")
        out["notes"].append({"id": n["id"], "t": n["t"], "t_end": n.get("t_end"), "when": when, "text": n["text"], "done": n.get("status") == "done",
                             "done_in": label(n["applied_in"]) if n.get("applied_in") else None, "clip_change": n.get("choice") is not None})
    nxt = (vs[-1]["n"] + 1) if vs else 1
    changes = sum(1 for n in open_n if n.get("choice") is not None)
    texts = len(open_n) - changes
    parts = ([f"{texts} note{'s' if texts != 1 else ''}"] if texts else []) + ([f"{changes} clip change{'s' if changes != 1 else ''}"] if changes else [])
    if stage == "cut" and not vs:
        can = (WORK_OF(work) / f"{name}.beatmap.json").exists()
        out["button"] = {"label": "Make the rough cut", "enabled": can and not running, "first": True,
                         "detail": "" if can else "There is no plan to cut from yet", "estimate": minutes_text(_PIPELINES["cut"][2]) if can else ""}
    else:
        out["button"] = {"label": f"Make {word} {nxt} from my notes", "enabled": bool(cur) and bool(parts) and not running, "first": False,
                         "detail": ", ".join(parts) if parts else "Add a note first",
                         "estimate": minutes_text(_PIPELINES["cut" if stage == "cut" else "preview"][2]) if parts else ""}
    if stage == "cut":
        import teaching
        starts = {b["id"]: b.get("start", 0.0) for b in _beat_list(work, name)}
        for m in teaching.seed(work, name):
            out["teaching"].append({"id": m["id"], "when": time_text(starts.get(m["beat"], 0.0)), "t": starts.get(m["beat"], 0.0),
                                    "term": m["term"], "why": m["why"], "status": m["status"]})
        out["teaching"].sort(key=lambda m: m["t"])
        import moments
        for m in moments.load(work, name):
            t = starts.get(m["beat"], 0.0)
            out["moments"].append({"id": m["id"], "when": time_text(t), "t": t, "kind": m["kind"], "text": m["text"], "why": m["why"], "status": m["status"]})
        out["moments"].sort(key=lambda m: m["t"])
    return out


def WORK_OF(work: str):
    import workflow
    return workflow.work_dir(work)


def _beat_list(work: str, name: str) -> list:
    import json
    try:
        return json.loads((WORK_OF(work) / f"{name}.beatmap.json").read_text(encoding="utf-8-sig")).get("beats", [])
    except (OSError, ValueError):
        return []


# ----------------------------------------------------------------------------- the Final step
def plain_warning(w: str) -> str:
    """finalrender's warnings, as sentences a person can act on (no file names)."""
    low = w.lower()
    if "no stitched preview" in low:
        return "Make the preview first: the final is made from it."
    if "plan changed since the preview" in low:
        return "The plan changed after the preview was made, so the final will not match what you watched."
    if "self-review" in low:
        return "Claude's own check of the preview found problems you may want to look at first."
    if "rebuild" in low:
        return "Some parts of the preview need to be made again before the final."
    if "not mixed" in low or "could not be found" in low:
        return "Some music or sound effects could not be found and will be left out."
    import re
    return re.sub(r"\s*\([^)]*\.(json|md|mp4)[^)]*\)", "", re.sub(r"\b[\w.-]+\.(json|md|mp4)\b", "", w)).strip().rstrip(":;,") or "Something needs a look before the final."


def final(work: str, name: str, running: bool = False) -> dict:
    """Everything the Final screen shows: warnings, the render button, the finals made, the publishing details and the archive step."""
    import json
    import os
    from urllib.parse import quote
    import finalrender
    import publish
    import shootplan
    import workflow
    wd = workflow.work_dir(work)
    key = key_of(work, name)
    st = finalrender.state(work, name)
    pd = publish.load(work, name)
    folder, _ = shootplan.footage_folder(work, name)
    done = None
    try:
        done = json.loads((wd / "FINALIZED.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    finals = [{"label": f"Final {i}", "file": f["file"], "dur": time_text(f["dur"]) if f.get("dur") else "", "size": f"{round(f['size_mb'])} MB",
               "when": __import__("time").strftime("%d %b %H:%M", __import__("time").localtime(f["mtime"]))}
              for i, f in enumerate(reversed(st["finals"]), start=1)]
    finals.reverse()
    latest = st["finals"][0] if st["finals"] else None
    warnings = [plain_warning(w) for w in st["warnings"]]
    ready = bool(st["ready"]) and not done
    why = "" if st["can_render"] else plain_warning(st["why_not"] or "no stitched preview yet")
    thumb = wd / "final" / "thumbnail-draft.jpg"
    out = {"key": key, "title": pd["title"] or st.get("title") or name, "archived": done is not None,
           "state": {"can_render": st["can_render"], "why_not": why, "warnings": warnings, "ready": ready},
           "button": {"label": "Render again" if latest else "Render final", "enabled": ready and not running,
                      "detail": why or ("Ready to render" if not warnings else f"{len(warnings)} thing{'s' if len(warnings) != 1 else ''} to look at first"),
                      "estimate": minutes_text(_PIPELINES["final"][2])},
           "finals": finals, "latest": None,
           "publish": {"titles": pd["titles"], "title_why": pd["title_why"], "pinned_comment": pd["pinned_comment"], "title": pd["title"], "description": pd["description"], "tags": pd["tags"],
                       "thumbnail_prompts": pd["thumbnail_prompts"], "thumbnail_text": pd["thumbnail_text"], "thumb": pd["thumb"],
                       "draft": f"/api/v2/thumbdraft?key={quote(key)}&v={int(os.path.getmtime(thumb))}" if thumb.exists() else None,
                       "button": "Ask Claude to redo" if pd["titles"] else "Ask Claude to write the publishing details", "enabled": not running},
           "archive": {"folder": str(folder) if folder else None, "done": ({"title": done.get("title"), "date": done.get("date")} if done else None),
                       "can": bool(latest) and bool(pd["title"]) and bool(folder) and not done and not running,
                       "why": "" if (latest and pd["title"] and folder) else
                       ("Render the final first." if not latest else "Choose the title first." if not pd["title"] else "Choose the footage folder first.")}}
    if latest:
        out["latest"] = {"video": f"/media/{quote(work)}/{quote(latest['file'])}", "dur": time_text(latest["dur"]) if latest.get("dur") else ""}
    out["scorecard"] = scorecard_view(work, name, latest, running)
    return out


def scorecard_view(work: str, name: str, latest: dict | None, running: bool) -> dict:
    """The Final screen's comparison with the reference videos: the rows of the last measurement, whether it is of the latest final, and the button."""
    import scorecard
    got = scorecard.load(work, name)
    stale = bool(got and latest and got.get("file") != latest["file"])
    return {"rows": got["rows"] if got else [], "n_refs": got["n_refs"] if got else len(scorecard.reference_videos()), "stale": stale,
            "button": {"label": "Measure again" if got else "Measure the final", "enabled": bool(latest) and not running,
                       "estimate": minutes_text(_PIPELINES["score"][2])}}


# ----------------------------------------------------------------------------- the Outline step
HEADER_FIELDS = [("title", "Title"), ("logline", "Logline"), ("thesis", "Thesis"), ("promise", "Promise"), ("thumbnail", "Thumbnail concept")]


def _summary(text: str, limit: int = 90) -> str:
    """The talking point: the first sentence of the suggested wording, shortened."""
    import re
    first = re.split(r"(?<![.]{3})(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def outline_view(work: str, name: str, running: bool = False) -> dict:
    """The outline screen: the header fields, one card per section with its shots, talking points, voice-over notes and graphic chips."""
    import outline
    import workflow
    m = outline.load(work, name)
    key = key_of(work, name)
    have = bool(m["sections"])
    header = []
    for field, label in HEADER_FIELDS:
        h = m["header"].get(field)
        text = h["text"] if h else (workflow.load(work, name).get("title", "") if field == "title" else "")
        header.append({"field": field, "label": label, "text": text, "line": h["line"] if h else None, "known": bool(h)})
    sections = []
    for s in m["sections"]:
        entries, cur = [], None
        for it in s["items"]:
            if it["type"] == "entry" or cur is None:
                cur = {"title": it["text"] if it["type"] == "entry" else None, "line": it["line"] if it["type"] == "entry" else None,
                       "raw": it["raw"] if it["type"] == "entry" else None, "shots": [], "talking": [], "vo": [], "chips": []}
                entries.append(cur)
                if it["type"] == "entry":
                    continue
            row = {"text": it["text"], "line": it["line"], "raw": it["raw"]}
            if it["type"] == "visual":
                cur["shots"].append(row)
            elif it["type"] == "aroll":
                cur["talking"].append({**row, "summary": _summary(it["text"])})
            elif it["type"] in ("vo", "teaching"):
                cur["vo"].append({**row, "teaching": it["type"] == "teaching"})
            elif it["type"] in ("graphic", "data"):
                cur["chips"].append({**row, "kind": it["type"]})
            elif it["type"] == "note":
                cur["vo"].append({**row, "note": True})
        secs = outline.seconds(s)
        sections.append({"key": s["key"], "line": s["line"], "title": s["title"], "icon": s["icon"], "time": minutes_text(secs / 60) if secs else "",
                         "entries": entries, "needs_shots": not any(it["type"] == "visual" for it in s["items"])})
    n = outline.gaps(m)
    return {"key": key, "has_outline": have, "header": header, "sections": sections, "gaps": n,
            "note": {"placeholder": "What should change?" if have else "What is the video about?"},
            "button": {"label": "Ask Claude to revise" if have else "Ask Claude to draft the outline", "enabled": not running,
                       "estimate": minutes_text(_PIPELINES["outline"][2])},
            "summary": (f"{n} section{'s' if n != 1 else ''} still need{'' if n != 1 else 's'} shot ideas" if n and have else "")}


# ----------------------------------------------------------------------------- the Footage step
def footage_view(work: str, name: str, running: bool = False, reading: bool = False) -> dict:
    """The footage screen: the folder, the recordings, what we have for each shot, and the one button that makes the rough cut."""
    from urllib.parse import quote
    import footageview
    import outline
    import reviewnotes
    import shotmatch
    key = key_of(work, name)
    rec = footageview.recordings(work, name, reading)
    has_outline = bool(outline.load(work, name)["sections"])
    cut_made = bool(reviewnotes.versions(work, name, "cut"))
    sections = shotmatch.rows(work, name) if has_outline else []
    miss = shotmatch.missing(work, name) if has_outline else []
    for r in rec["rows"]:
        r["frame"] = f"/api/v2/clipframe?key={quote(key)}&rel={quote(r['ref'])}&t=1"
    for sec in sections:
        for it in sec["items"]:
            for c in it.get("candidates", []):
                c["frame"] = f"/api/v2/clipframe?key={quote(key)}&rel={quote(c['rel'])}&t={c['t']:.1f}"
                c["at"] = time_text(c["t"])
            if it.get("chosen"):
                it["chosen"]["frame"] = f"/api/v2/clipframe?key={quote(key)}&rel={quote(it['chosen']['rel'])}&t={it['chosen']['t']:.1f}"
    if not rec["folder"]:
        why = "Choose the folder you recorded into first."
    elif not rec["total"]:
        why = "Write the outline first." if not has_outline else "There are no recordings in that folder yet."
    else:
        why = ""
    steps = []
    if rec["unread"]:
        steps.append(f"reads {rec['unread']} recording{'s' if rec['unread'] != 1 else ''}")
    if rec["total"] > rec["looked"]:
        steps.append("looks at what is in the footage")
    if not has_outline:
        steps.append("writes an outline from what you said")
    steps += ["matches your clips to the outline", "cuts them together"]
    return {"key": key, "folder": {"path": rec["folder"], "short": " › ".join(__import__("pathlib").Path(rec["folder"]).parts[-2:]) if rec["folder"] else "",
                                   "guessed": rec["how"] == "guessed", "set": bool(rec["folder"])},
            "recordings": {k: rec[k] for k in ("total", "read", "unread", "looked", "ignored", "thin", "rows")}, "has_outline": has_outline, "sections": sections,
            "missing": miss,
            "button": {"label": "Make the rough cut again" if cut_made else "Write the outline and make the rough cut" if not has_outline else "Make the rough cut", "enabled": not why and not running, "why": why,
                       "detail": ("First it " + ", ".join(steps[:-1]) + " and " + steps[-1] + ".") if not why and len(steps) > 1 else "",
                       "estimate": minutes_text(_PIPELINES["cut"][2] + (8 if rec["unread"] else 0))},
            "summary": (f"{rec['total']} recording{'s' if rec['total'] != 1 else ''}"
                        + (f", {rec['unread']} not read yet" if rec["unread"] else "") + (f", {rec['ignored']} left out" if rec["ignored"] else "") if rec["total"] else "")}
