"""Workflow state for a video: stages, settings, history (see docs/workflow.md; every stage is a draft).

State lives in  _editor\\work\\<work>\\<name>.workflow.json:
  {"settings": {...}, "history": [...]}   (a "gates" key from an older version may still be in old files; it is ignored)
A stage is done when the file behind it exists.

Python stdlib only. Used by review_app/server.py; also runnable:  python workflow.py <work> <name>
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent          # not resolve(): that turns Z:\ into a network share
import config
WORK = config.WORK
DEFAULT_SETTINGS = {
    "preview_size": [960, 540],          # half-size renders (the creator, 2026-10-21); change if text/faces are hard to judge
    "max_parallel": 3,                   # sub-agents at once (the creator's rule)
    "graphics_per_minute": 0.5,          # one per ~2 min of talking ...
    "graphics_extra": 2,                 # ... plus title and end cards
    "min_visible_s": 1.0,                # self-review: nothing flashes shorter than this
    "read_s_per_word": 0.3,              # self-review: reading time per word ...
    "read_pad_s": 0.4,                   # ... plus this
    "lip_tolerance_frames": 2,           # self-review: lips vs voice
    "build_model": "sonnet",             # background Claude runs for sections that need graphics designed
    "build_effort": "medium",            # low | medium | high | xhigh | max
    "build_budget_usd": 2.0,             # soft cap per section run (checked between turns, so it can overshoot)
    "critic_model": "opus",              # a second, stronger Claude that LOOKS at each built motion explainer and lists what to fix ("off" = no critic pass)
    "critic_effort": "medium",           # low | medium | high | xhigh | max
    "critic_budget_usd": 1.0,            # soft cap for the critic's run
    "voice_chain": True,                 # final render: The creator's "V2 warmer, less bright" voice processing
    "music_below_speech_db": 26.0,       # final render: music level under the speech (LU), from the v3 feedback
    "duck_db": 9.0,                      # final render: extra dip of the music while the creator talks
    "selfreview_after_stitch": True,     # stitching starts the self-review (flashes, text, faces, repeated words, lips, dead air, picture/sound length) on the new preview
    "music_in_preview": True,            # the stitched preview carries the music beds from the beat map (same level and ducking as the final), so the music is judged before the final
    "manual_hours_before": 0.0,          # dashboard: hours this kind of video used to take by hand (the creator's own number)
    "hours_actual": 0.0,                 # dashboard: hours it took this time with the process (the creator's own number)
    "hourly_rate_usd": 0.0,              # dashboard: what an hour of the creator's time is worth, to put a dollar figure on the saving
    "chat_price_in": 0.0,                # dashboard: USD per million tokens for chat sessions (input and cache writes); 0 = no estimate
    "chat_price_cache": 0.0,             # ... cache reads
    "chat_price_out": 0.0,               # ... output
}
CHOICES = {"build_model": ("sonnet", "opus", "haiku", "fable"), "build_effort": ("low", "medium", "high", "xhigh", "max"),
           "critic_model": ("off", "opus", "sonnet", "fable"), "critic_effort": ("low", "medium", "high", "xhigh", "max")}

# Stages in order. A stage is done when the file behind it exists. Nothing waits for a sign-off.
STAGES = [
    {"id": "script", "title": "Script", "file": "{name}.script.md",
     "what": "The script, with a line id (S01, S02...) on every line.",
     "make": "Ask Claude: \"write the script for <video idea>\" (it uses the hook library)."},
    {"id": "shootplan", "title": "Shoot plan", "file": "{name}.shootplan.json",
     "what": "The shot list for filming: every script line gets a recording and a picture, with what is already shot ticked off.",
     "make": "Ask Claude: \"write the shoot plan from the script\". Tick shots off in the Shoot plan tab as you film."},
    {"id": "clips", "title": "Clips", "file": "{name}.clips.json",
     "what": "Every raw clip transcribed, best takes picked, and what each clip (or part of a clip) is about.",
     "make": "Ask Claude to transcribe the footage and build the clip cards for you to correct."},
    {"id": "beatmap", "title": "Beat map", "file": "{name}.beatmap.json",
     "what": "What is said and what is on screen, beat by beat, with proposed graphics (kept few).",
     "make": "Ask Claude to build the beat map from the script and clips."},
    {"id": "storyboard", "title": "Storyboard", "file": "storyboard/index.html", "dir": "storyboard",
     "what": "One frame per beat for the whole video, graphics shown on your real frame.",
     "make": "Ask Claude to build the storyboard from the beat map."},
    {"id": "graphicsplan", "title": "Graphics plan", "file": "{name}.graphicsplan.json",
     "what": "One card per graphic: what it shows and which look it gets (3D depth, sticker caption, UI explainer, kinetic type, plain card). Choose the look before anything is built: a graphic is expensive to rebuild.",
     "make": "Open the Graphics tab: the plan is made from the beat map; choose a look for each graphic."},
    {"id": "build", "title": "Build", "file": "{name}.sections.status.json",
     "what": "Sections built by background Claude runs (at most 3 at a time), half-size renders only.",
     "make": "Starts from the beat map. The Build tab shows how many sections need a Claude run before you start."},
    {"id": "graphicsreview", "title": "Graphics review", "file": "{name}.graphicsreview.json",
     "what": "Watch each built graphic in context and mark it OK, or say what to change (Claude rebuilds it with your note). Graphics render once at full size, so this comes before the final.",
     "make": "Open the Graphics tab after the build."},
    {"id": "selfreview", "title": "Self-review", "file": "{name}.selfreview.json",
     "what": "Claude checks its own work: repeated animations, flashes, late text, faces covered, repeated words, lip drift.",
     "make": "Runs after the build, before you see it."},
    {"id": "review", "title": "Your review", "file": "{name}.preview-half.mp4",
     "what": "You watch the whole half-size video and pin notes.",
     "make": "Appears after the self-review."},
    {"id": "final", "title": "Final render", "file": None,
     "what": "Full-quality render from the stitched preview. It warns about anything unfinished but only needs the preview to exist.",
     "make": "Available once the stitched preview exists."},
]


# ----------------------------------------------------------------------------- files
def _safe(s: str) -> str:
    if not s or "/" in s or "\\" in s or ".." in s:
        raise ValueError(f"bad name {s!r}")
    return s


def work_dir(work: str) -> Path:
    d = WORK / _safe(work)
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def state_path(work: str, name: str) -> Path:
    return work_dir(work) / f"{_safe(name)}.workflow.json"


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


def stage_path(wd: Path, name: str, st: dict):
    """The file behind a stage, or for a folder stage (the storyboard: stills + index.html) the folder itself."""
    if st.get("dir"):
        return wd / st["dir"]
    if st["id"] == "review":                                    # every stitch has its own file name (builder.py), so ask stitch.json which one is current: the review stage said "missing" for every stitch after the first (the creator, 2026-10-27)
        try:
            f = json.loads((wd / f"{name}.stitch.json").read_text(encoding="utf-8-sig")).get("file")
            if f and (wd / f).exists():
                return wd / f
        except (OSError, ValueError):
            pass
    return wd / st["file"].format(name=name) if st.get("file") else None


# ----------------------------------------------------------------------------- summaries
LINE_RE = re.compile(r"^\W*(S\d{2,3})\b", re.M)


def summarize(stage_id: str, wd: Path, name: str, settings: dict) -> dict:
    """A few human facts about the file behind a stage, tolerant of a schema that is still settling."""
    st = next(s for s in STAGES if s["id"] == stage_id)
    p = stage_path(wd, name, st)
    out = {"lines": [], "warnings": []}
    if p is None or not (p.is_dir() if st.get("dir") else p.exists()):
        return out
    L, W = out["lines"], out["warnings"]
    if stage_id == "script":
        txt = p.read_text(encoding="utf-8-sig")
        ids = LINE_RE.findall(txt)
        L.append(f"{len(ids)} script lines with ids, {len(txt.split())} words")
        fills = len(re.findall(r"\[FILL", txt[txt.find("\n##"):] if "\n##" in txt else txt))      # the header only explains the marker
        if fills:
            W.append(f"{fills} [FILL] placeholder{'s' if fills != 1 else ''} still open: facts only you can supply")
        if not ids:
            W.append("no line ids (S01, S02...): later stages refer to lines by id")
        lg = re.search(r"^Logline([^:\n]*):[ \t]*(\S.*)$", txt, re.M)
        if not lg:
            W.append("no logline: one sentence on who is trying to do what, what stands in the way and what is at stake (Script tab)")
        elif "draft" in lg.group(1).lower():
            W.append("the logline is still marked as a draft (Script tab)")
    elif stage_id == "shootplan":
        try:                                          # the real numbers live in shootplan.py
            import shootplan
            s = shootplan.state(wd.name, name)
            c = s["counts"]
            L.append(f"{c['shots']} shots to film: {c['done']} done; {c['must_done']} of {c['must']} must-have shots in hand; "
                     f"{c['a_roll_done']} of {c['a_roll']} recording sessions done" + (f"; {c['pickups_open']} pickup(s) open" if c["pickups_open"] else ""))
            W.extend(s["warnings"])
        except (KeyError, TypeError, ValueError, ImportError):
            L.append(f"{len((read_json(p, {}) or {}).get('shots', []))} shots")
    elif stage_id == "clips":
        j = read_json(p, {}) or {}
        clips = j.get("clips", [])
        spans = sum(len(c.get("spans", [])) or 1 for c in clips)
        low = sum(1 for c in clips for s in (c.get("spans") or [c]) if (s.get("confidence") or 1) < 0.6)
        L.append(f"{len(clips)} clips, {spans} topic spans, {len(j.get('corrections', []))} corrections by you")
        if low:
            W.append(f"{low} span{'s' if low != 1 else ''} with low confidence: check those first")
    elif stage_id == "beatmap":
        j = read_json(p, {}) or {}
        try:                                          # the real numbers and checks live in beatmap.py
            import beatmap
            s = beatmap.stats(j, settings)
            L.append(f"v{j.get('version', 1)}: {s['beats']} beats, {s['runtime_s'] / 60:.1f} min, {s['graphics']} graphics "
                     f"(budget {s['budget']}) + {s['cards']} title/end cards, {s['broll']} B-roll")
            if s["graphics"] > s["budget"]:
                W.append(f"{s['graphics']} graphics is over your budget of {s['budget']} for this length: offer the weakest to cut")
            fixes = [r for r in beatmap.check(j, settings) if r["level"] == "fix"]
            if fixes:
                W.append(f"{len(fixes)} thing{'s' if len(fixes) != 1 else ''} to fix in the plan (see the Beat map tab)")
        except (KeyError, TypeError, ValueError):     # a hand-written beat map without the full schema
            beats = j.get("beats", [])
            L.append(f"{len(beats)} beats, {sum(1 for b in beats if b.get('graphic'))} graphics")
    elif stage_id == "storyboard":
        try:                                          # the real numbers live in storyboard.py
            import storyboard
            s = storyboard.state(wd.name, name)
            c = s["counts"]
            L.append(f"{s['total']} frames: {c['ok']} OK, {c['change']} need changes, {c['unseen']} not looked at yet")
            if c["unseen"] or c["change"]:
                W.append(f"{c['unseen'] + c['change']} frame{'s' if c['unseen'] + c['change'] != 1 else ''} not marked OK")
            if s["stale"]:
                W.append("the beat map changed since the storyboard was built: update it")
            if s["fix_flags"]:
                W.append(f"{s['fix_flags']} frame{'s' if s['fix_flags'] != 1 else ''} with a problem (e.g. a graphic on your face)")
        except (KeyError, TypeError, ValueError, ImportError):
            files = [f for f in p.rglob("*") if f.is_file()]
            L.append(f"{sum(1 for f in files if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'))} frames")
    elif stage_id == "graphicsplan":
        try:                                          # the real numbers live in gfxplan.py
            import gfxplan
            s = gfxplan.state(wd.name, name)
            c = s["counts"]
            L.append(f"{c['graphics']} graphics: {c['ok']} OK, {c['change']} need a change, {c['cut']} cut, {c['undecided']} not decided; {c['styled']} have a look chosen")
            W.extend(s["warnings"])
        except (KeyError, TypeError, ValueError, ImportError):
            L.append("graphics plan")
    elif stage_id == "graphicsreview":
        try:
            import gfxplan
            s = gfxplan.review_state(wd.name, name)
            c = s["counts"]
            L.append(f"{c['graphics']} graphics: {c['built']} built, {c['ok']} marked OK, {c['change']} need a change, {c['unseen']} not looked at yet")
            W.extend(s["warnings"])
        except (KeyError, TypeError, ValueError, ImportError):
            L.append("graphics review")
    elif stage_id == "build":
        j = read_json(p, {}) or {}
        secs = j.get("sections", [])
        n = lambda s: sum(1 for x in secs if x.get("status") == s)
        cost = sum(x.get("cost_usd") or 0 for x in secs)
        L.append(f"{len(secs)} sections: {n('done')} built, {n('running')} building, {n('queued')} waiting, {n('failed')} failed"
                 + (f", ${cost:.2f} spent on Claude runs" if cost else ""))
        if n("running") > settings["max_parallel"]:
            W.append("more sections running than the limit: stop one")
        bad = [x["id"] for x in secs if (x.get("audit") or {}).get("ok") is False]
        if bad:
            W.append(f"{', '.join(bad)}: something outside the section's folder changed while it ran (see the Build tab)")
        if n("failed") or n("interrupted") or n("cancelled"):
            W.append(f"{n('failed') + n('interrupted') + n('cancelled')} section(s) not built (failed, interrupted or cancelled)")
        left = [x["id"] for x in secs if x.get("left_out")]
        if left:
            W.append(f"{', '.join(left)}: Claude left out a graphic (see its report)")
    elif stage_id == "selfreview":
        try:                                          # the real checks and verdict live in selfreview.py
            import selfreview
            s = selfreview.state(wd.name, name)
            c = s["counts"]
            ran = sum(1 for x in s["checks"] if x["ran"])
            L.append(f"{c['fix']} to fix, {c['look']} to look at, {c['dismissed']} dismissed by you; {ran} of {len(s['checks'])} checks ran"
                     + ("; clean pass" if s["clean"] else ""))
            if s["stale"]:
                W.append("the preview changed after this self-review: run it again")
            if c["fix"]:
                W.append(f"{c['fix']} problem{'s' if c['fix'] != 1 else ''} still to fix (see the Self-review tab)")
            if not s["all_checks_ran"]:
                W.append("not every check ran, so this is not a clean pass: " + ", ".join(x["label"].lower() for x in s["checks"] if not x["ran"]))
        except (KeyError, TypeError, ValueError, ImportError):
            j = read_json(p, {}) or {}
            L.append(f"{len(j.get('findings', []))} findings")
    elif stage_id == "review":
        L.append(f"{p.stat().st_size / 1e6:.0f} MB")
    return out


# ----------------------------------------------------------------------------- state
def load(work: str, name: str) -> dict:
    s = read_json(state_path(work, name), None) or {}
    s.setdefault("settings", {})
    s.setdefault("history", [])
    return s


def save(work: str, name: str, s: dict):
    write_json(state_path(work, name), s)


def _log(s: dict, what: str):
    s["history"].append({"t": datetime.now().isoformat(timespec="seconds"), "what": what})


def effective(saved: dict) -> dict:
    """The settings a video runs with: the defaults, then the graphics models chosen in Settings (claudemodels), then what this video saved itself."""
    import claudemodels
    return {**DEFAULT_SETTINGS, **claudemodels.graphics_defaults(), **saved}


def state(work: str, name: str) -> dict:
    """Where the video is: one row per stage (done / waiting), warnings, and the next thing to do. Nothing waits for a sign-off."""
    wd = work_dir(work)
    s = load(work, name)
    settings = effective(s["settings"])
    stages = []
    for st in STAGES:
        if st["id"] in ("graphicsplan", "graphicsreview"):        # the plan and the review files are made from the beat map as soon as it exists
            try:
                import gfxplan
                (gfxplan.ensure_plan if st["id"] == "graphicsplan" else gfxplan.ensure_review)(work, name)
            except Exception:
                pass
        p = stage_path(wd, name, st)
        exists = bool(p) and (p.is_dir() if st.get("dir") else p.exists())
        info = summarize(st["id"], wd, name, settings)
        stages.append({"id": st["id"], "title": st["title"], "what": st["what"], "make": st["make"],
                       "file": str(p) if p else None, "exists": exists, "summary": info["lines"], "warnings": info["warnings"],
                       "status": "done" if exists else "waiting"})
    by = {r["id"]: r for r in stages}
    # The final render needs a stitched preview to start from; a final newer than that preview means it is done.
    by["final"]["status"] = "waiting"
    if by["review"]["exists"]:
        by["final"]["status"] = "ready"
        preview = stage_path(wd, name, next(x for x in STAGES if x["id"] == "review"))
        if any(f.stat().st_mtime > preview.stat().st_mtime for f in wd.glob("* v*(1080p).mp4")):
            by["final"]["status"] = "done"
    if by["review"]["exists"] and not by["selfreview"]["exists"]:
        by["review"]["warnings"].append("the self-review has not run for this video")
    elif by["review"]["exists"] and by["selfreview"]["warnings"]:
        by["review"]["warnings"].append("the self-review is not a clean pass yet (see the Self-review tab)")
    nxt = next((r for r in stages if r["id"] not in ("shootplan", "final") and not r["exists"]), None)
    if nxt:
        nxt_out = {"stage": nxt["id"], "title": nxt["title"], "status": nxt["status"], "hint": nxt["make"]}
    elif by["final"]["status"] == "done":
        nxt_out = {"stage": "final", "title": "Final render", "hint": "Everything is done."}
    else:
        nxt_out = {"stage": "final", "title": "Final render", "hint": "Watch the stitched preview, then render the final."}
    since = {m: projectstore.changes_since(wd, name, m) for m in ("build", "stitch", "final")}
    return {"work": work, "name": name, "dir": str(wd), "settings": settings, "stages": stages, "next": nxt_out, "history": s["history"][-30:],
            "since": {m: c for m, c in since.items() if c}}


def set_settings(work: str, name: str, new: dict) -> dict:
    s = load(work, name)
    for k, v in new.items():
        if k not in DEFAULT_SETTINGS:
            raise ValueError(f"unknown setting {k!r}")
        d = DEFAULT_SETTINGS[k]
        if k in CHOICES:
            if v not in CHOICES[k]:
                raise ValueError(f"{k} must be one of {', '.join(CHOICES[k])}")
        elif isinstance(d, bool):
            v = bool(v)
        elif isinstance(d, list):
            v = [int(x) for x in v]
            if len(v) != 2 or min(v) < 160:
                raise ValueError("preview_size must be [width, height]")
        elif isinstance(d, int):
            v = int(v)
            if v < 1 or (k == "max_parallel" and v > 3):
                raise ValueError(f"{k}: must be 1..3" if k == "max_parallel" else f"{k}: must be at least 1")
        else:
            v = float(v)
            if v < 0:
                raise ValueError(f"{k} must not be negative")
        s["settings"][k] = v
    _log(s, "changed settings: " + ", ".join(f"{k}={s['settings'][k]}" for k in new))
    save(work, name, s)
    return state(work, name)


def list_videos() -> list[dict]:
    """Videos the Workflow tab can show: any with a workflow.json or a script. (The review tabs list
    videos by edit.json instead; a brand-new video has neither until it gets a script.)"""
    out = []
    for d in sorted(WORK.iterdir()) if WORK.is_dir() else []:        # a new workspace has no work folder until the first video
        if not d.is_dir():
            continue
        names = sorted({p.name[:-len(".workflow.json")] for p in d.glob("*.workflow.json")} |
                       {p.name[:-len(".script.md")] for p in d.glob("*.script.md")})
        if names:
            out.append({"work": d.name, "names": names})
    return out


SLUG_RE = re.compile(r"[^a-z0-9]+")


def create(title: str) -> dict:
    """New video: a work folder and an empty workflow state. The title becomes the folder / file name."""
    title = (title or "").strip()
    if len(title) < 3:
        raise ValueError("give the video a short name")
    slug = SLUG_RE.sub("-", title.lower()).strip("-")[:48] or "video"
    d = WORK / slug
    if d.exists() and any(d.glob("*.workflow.json")):
        raise ValueError(f"{slug!r} already exists")
    d.mkdir(parents=True, exist_ok=True)
    s = {"title": title, "settings": {}, "history": []}
    _log(s, f"created: {title}")
    write_json(d / f"{slug}.workflow.json", s)
    return {"work": slug, "name": slug}


if __name__ == "__main__":
    import sys
    print(json.dumps(state(sys.argv[1], sys.argv[2]), indent=1))
