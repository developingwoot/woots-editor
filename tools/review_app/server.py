"""the channel review app: a local web UI on top of the editing pipeline.

The video workflow's control room: Outline, Footage, Rough cut, Preview, Final and Shorts (screens in static/v2/, stages from tools/workflow.py).
Review-and-decisions layer, not an editor: watch a cut, leave notes, and Claude applies them in background runs; ffmpeg and HyperFrames do the rendering.
Every stage is a draft: nothing waits for a sign-off.

Usage:
    python server.py [--port 8765]   (listens on this computer only)
    (or double-click review_app\\start.bat)

Python stdlib only. Reads/writes the plan JSON files in _editor\\work\\<video>\\ and the
CONFIG block of _editor\\graphics\\<video>\\<graphic>\\index.html.
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

APP = Path(os.path.abspath(__file__)).parent   # not resolve(): that turns Z:\ into a network share
EDITOR = APP.parents[1]                      # the code root (this repo); data paths come from config
sys.path.insert(0, str(EDITOR / "tools"))
import config  # noqa: E402
WORK = config.WORK
TOOLS = EDITOR / "tools"
PY = config.PYTHON                            # the interpreter running the app, unless WOOTS_PYTHON / config.local.json says otherwise
STATIC = APP / "static"
sys.path.insert(0, str(TOOLS))                    # footage_cfg, roughcut (pure Python helpers)
_STARTED = time.time()


def _static_newest() -> float:
    return max([f.stat().st_mtime for f in (Path(__file__).parent / "static").rglob("*") if f.is_file()] or [0.0])


def _busy() -> bool:
    """True while anything is running that a restart would kill: a pipeline or graphic render, a section build, a queued build."""
    try:
        return any(not j.get("done", True) for j in _jobs.values()) or bool(builder._running) or bool(builder._queue) or accuracy.is_running()
    except Exception:                                     # noqa: BLE001
        return False


def _code_newest() -> float:
    """Newest modification time of the app's own code (the tools and the page files): a copy that started before it is running OLD code."""
    newest = 0.0
    for d, pat in ((TOOLS, "*.py"), (Path(__file__).parent, "*.py"), (Path(__file__).parent / "static", "*")):
        for f in d.glob(pat):
            if f.is_file():
                newest = max(newest, f.stat().st_mtime)
    return newest


import guard                                      # noqa: E402  (who may talk to the app)
import footage_cfg                                # noqa: E402
import channel                                    # noqa: E402  (names in the prompts)
import projectstore                               # noqa: E402  (what changed, who changed it, undo: ADR 0005)
projectstore.actor = "user"                        # writes made through the app's pages are the creator's
import workflow                                   # noqa: E402  (stages, settings)
import claudemodels                               # noqa: E402  (which model and effort each kind of Claude run uses)
import views                                      # noqa: E402  (plain-language view models for /v2)
import reviewnotes                                # noqa: E402  (v2 notes and versions)
import shotmatch                                  # noqa: E402  (v2: what we have for each shot)
import framing                                  # noqa: E402  (v2: punch-in zooms that keep the eyes on one line)
import cutreview                               # noqa: E402  (v2: a read of the cut for contradictions and repeats)
import coldopen                               # noqa: E402  (v2: the cold open before the intro)
import takes                                  # noqa: E402  (v2: the passages the creator says more than once)
import recut                                     # noqa: E402  (v2: the cut from whole recordings, ADR 0009)
import outline                                    # noqa: E402  (v2 outline: both script formats)
import publish                                    # noqa: E402  (v2 publishing details)
import teaching                                   # noqa: E402  (v2 teaching moments)
import clipmap                                    # noqa: E402  (takes -> script lines, the creator's corrections)
import beatmap                                    # noqa: E402  (the plan: what is said / on screen, graphics, checks)
import platformx                                  # noqa: E402  (the few operating-system specifics)
import clauderun                                  # noqa: E402  (the one place a background Claude command is built)
import builder                                    # noqa: E402  (stage 5: sections, 3-slot scheduler, headless Claude runs)
import usage                                      # noqa: E402  (Dashboard: Claude cost, free local work, time saved)
import musicaudition                              # noqa: E402  (Build tab: hear another music track in place of a bed)
import resolve_export                             # noqa: E402  (Dashboard: the stitched video as a rough-cut timeline for DaVinci Resolve)
import finalrender                                # noqa: E402  (stage 8: the full-quality render)
import accuracy                                   # noqa: E402  (Beat map tab: Opus checks what is taught for accuracy)
import shortsapp                                  # noqa: E402  (Shorts tab: vertical shorts from a finished video)
import shortsplan                                 # noqa: E402  (how many shorts a video deserves, and the rules for them: ADR 0006)
import skillrules                                # noqa: E402  (the numbers shorts are made with)
import shortsview                                 # noqa: E402  (the v2 Shorts screen)

_lock = threading.Lock()                     # one writer at a time (several browser tabs)
_probe_cache: dict = {}
_jobs: dict = {}


# ----------------------------------------------------------------------------- helpers
def find_exe(name: str) -> str | None:
    exe = shutil.which(name)
    if exe:
        return exe
    # Shells started before the winget FFmpeg install don't have it on PATH.
    for base in [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
                 *Path(os.environ.get("LOCALAPPDATA", "")).glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin")]:
        p = Path(base) / f"{name}.exe"
        if p.exists():
            return str(p)
    return None


FFPROBE = find_exe("ffprobe")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data, indent=1):
    """Atomic UTF-8 write without BOM (PowerShell's BOM broke json.loads once)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    config.replace_retry(tmp, path)


def work_dir(work: str) -> Path:
    d = WORK / config.safe_part(work)
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def plan_file(work: str, name: str, ext: str) -> Path:
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("bad name")
    return work_dir(work) / f"{name}.{ext}.json"


# ----------------------------------------------------------------------------- graphics CONFIG
CONFIG_RE = re.compile(r"(// CONFIG:BEGIN.*?const CONFIG = )(.*?)(;\s*\n\s*// CONFIG:END)", re.S)


def read_config(html: str):
    m = CONFIG_RE.search(html)
    return json.loads(m.group(2)) if m else None


def fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def resolve_t(cfg, v):
    """A clip edge: seconds, a beat name, or [beat name, offset]."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        return float(cfg["beats"][v[0]]) + float(v[1])
    return float(cfg["beats"][v])


def write_config(html: str, cfg: dict) -> str:
    """Replace the CONFIG block and the clip timing attributes HyperFrames reads from the markup."""
    # One line per section keeps the block readable in the HTML.
    body = "{\n" + ",\n".join(f"      {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
                              for k, v in cfg.items()) + "\n    }"
    html = CONFIG_RE.sub(lambda m: m.group(1) + body + m.group(3), html, count=1)
    dur = resolve_t(cfg, "end")

    def set_attrs(el_id, start, length):
        nonlocal html
        pat = re.compile(r'(<div\b[^>]*\bid="%s"[^>]*>)' % re.escape(el_id), re.S)
        m = pat.search(html)
        if not m:
            return
        tag = m.group(1)
        if start is not None:
            tag = re.sub(r'data-start="[^"]*"', f'data-start="{fmt(start)}"', tag)
        tag = re.sub(r'data-duration="[^"]*"', f'data-duration="{fmt(length)}"', tag)
        html = html[:m.start()] + tag + html[m.end():]

    set_attrs("stage", None, dur)
    for el_id, (a, b) in (cfg.get("clips") or {}).items():
        a, b = resolve_t(cfg, a), resolve_t(cfg, b)
        set_attrs(el_id, a, b - a)
    # Mirror the copy into the markup too: HyperFrames picks font glyphs from the static text, so
    # text that only JS sets (a "✓") rendered in a fallback font.
    for el_id, text in (cfg.get("text") or {}).items():
        pat = re.compile(r'(<(div|span)\b[^>]*\bid="%s"[^>]*>)(.*?)(</\2>)' % re.escape(el_id), re.S)
        html = pat.sub(lambda m: m.group(1) + text + m.group(4), html, count=1)
    return html


# ----------------------------------------------------------------------------- project bundle


def tool_env():
    """Environment for the pipeline tools: UTF-8 output and FFmpeg on PATH (the winget install isn't
    on PATH in shells started before it)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if FFPROBE:
        env["PATH"] = str(Path(FFPROBE).parent) + os.pathsep + env.get("PATH", "")
    return env


# ----------------------------------------------------------------------------- footage library
SKIP_DIRS = {"_editor", "$recycle.bin", "system volume information", "node_modules"}


def footage_file(work, name) -> Path:
    return plan_file(work, name, "footage")


def list_drives() -> list[str]:
    try:
        return [d for d in os.listdrives()]
    except (AttributeError, OSError):
        return [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


def list_dir(path: str, files: bool = False) -> dict:
    """Folder browser: sub-folders of a directory (empty path = the drives). With files=True the video files in it too, as {name, path, mb}."""
    if not path:
        return {"path": "", "parent": None, "dirs": [{"name": d, "path": d} for d in list_drives()], "videos": 0}
    p = Path(path)
    if not p.is_dir():
        raise ValueError(f"not a folder: {path}")
    dirs, vids, vfiles = [], 0, []
    try:
        for e in os.scandir(p):
            if e.is_dir(follow_symlinks=False):
                if not e.name.startswith((".", "$")) and e.name.lower() not in SKIP_DIRS - {"_editor"}:
                    dirs.append({"name": e.name, "path": str(Path(e.path))})
            elif Path(e.name).suffix.lower() in footage_cfg.VIDEO_EXT:
                vids += 1
                if files:
                    vfiles.append({"name": e.name, "path": str(Path(e.path)), "mb": round(e.stat().st_size / 1e6)})
    except PermissionError:
        raise ValueError(f"no permission to read {path}")
    dirs.sort(key=lambda d: d["name"].lower())
    vfiles.sort(key=lambda f: f["name"].lower())
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "dirs": dirs, "videos": vids, **({"files": vfiles} if files else {})}


def probe_clip(path: Path) -> dict:
    """Duration / size / fps / audio of a clip, cached by (path, size, mtime) in the process."""
    st = path.stat()
    key = ("clip", str(path), st.st_size, st.st_mtime)
    if key in _probe_cache:
        return _probe_cache[key]
    info = {"dur": None, "w": None, "h": None, "fps": None, "audio": False}
    if FFPROBE:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                              "stream=codec_type,width,height,avg_frame_rate:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True).stdout
        try:
            j = json.loads(out)
            for s in j.get("streams", []):
                if s.get("codec_type") == "video" and info["w"] is None:
                    info["w"], info["h"] = s.get("width"), s.get("height")
                    n, _, d = (s.get("avg_frame_rate") or "0/1").partition("/")
                    info["fps"] = round(float(n) / float(d), 2) if float(d or 1) else None
                elif s.get("codec_type") == "audio":
                    info["audio"] = True
            info["dur"] = round(float(j["format"]["duration"]), 3)
        except (ValueError, KeyError):
            pass
    _probe_cache[key] = info
    return info



def footage_path_ok(work, name, rel) -> Path:
    cfg = read_json(footage_file(work, name), {}) or {}
    if not cfg.get("folder"):
        raise ValueError("no footage folder chosen")
    folder = Path(cfg["folder"])
    p = folder / rel
    if not config.inside(folder, p) or p.suffix.lower() not in (footage_cfg.VIDEO_EXT | {".wav", ".m4a", ".mp3", ".aac", ".flac"}) or not p.is_file():
        raise ValueError("not a clip in the footage folder")
    return p



def summarize_take(tr: dict, dur) -> dict:
    from roughcut import find_retakes
    words, segs = tr.get("words", []), tr.get("segments", [])
    s = {"dur": dur, "words": len(words), "text": tr.get("text", "")}
    if not words:
        return {**s, "first": None, "last": None, "restarts": 0, "pauses": 0, "wpm": 0, "trim": None, "list": []}
    first, last = words[0]["start"], words[-1]["end"]
    flags = find_retakes(segs)
    pauses = sum(1 for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 1.2)
    s.update({"first": first, "last": last, "restarts": len(flags), "restart_at": [round(f["start"], 1) for f in flags],
              "pauses": pauses, "wpm": round(len(words) / ((last - first) / 60)) if last > first else 0,
              "trim": [round(max(0.0, first - 0.4), 2), round(min(dur or last + 0.6, last + 0.6), 2)],
              "list": [[w["word"], w["start"], w["end"]] for w in words]})
    return s


def _transcribe(job, work, name, paths, items, man) -> bool:
    """Run Parakeet over the manifest (one model load) and save each take's words into footage.json. True when it worked."""
    p = subprocess.Popen([str(PY), str(TOOLS / "analyze_takes.py"), str(man)], cwd=TOOLS, env=tool_env(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        job["log"] = (job["log"] + line)[-30000:]
    if p.wait() != 0:
        return False
    with _lock:
        cfg = read_json(footage_file(work, name), {}) or {}
        an = cfg.setdefault("analysis", {})
        for (rel, pth), it in zip(paths, items):
            tr = read_json(Path(it["out"]))
            if tr:
                an[rel] = summarize_take(tr, probe_clip(pth)["dur"])
        write_json(footage_file(work, name), cfg)
    return True


def _look_at_footage(job, work, name) -> bool:
    """Run the vision library over every recording not looked at yet (brolllib.py skips the ones it has)."""
    v = subprocess.Popen([str(PY), str(TOOLS / "brolllib.py"), work, "--name", name], cwd=TOOLS, env=tool_env(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in v.stdout:
        if line.startswith("["):
            job["log"] = (job["log"] + line)[-30000:]
    return v.wait() == 0



# ----------------------------------------------------------------------------- clips (script <-> takes)



def start_final(work, name):
    if any(j.get("pipeline") and not j["done"] for j in _jobs.values()):
        raise ValueError("another job is running: wait for it to finish")
    work_dir(work)
    st = finalrender.state(work, name)
    if not st["can_render"]:
        raise ValueError(st["why_not"])
    if not st["ready"]:
        raise ValueError("; ".join(st["warnings"]) or "nothing to render yet")
    job = {"id": uuid.uuid4().hex[:8], "pipeline": "final", "log": "", "done": False, "ok": None, "step": 0,
           "steps": ["picture at full quality", "speech (voice chain)", "music + sound effects", "loudness + final file", "checks"],
           "out": None, "started": time.time(), "work": work, "name": name}
    _jobs[job["id"]] = job

    def run():
        try:
            if os.environ.get("WOOTS_FAKE_CLAUDE"):          # tests: a copy of the stitched preview stands in for the render
                import watchnotes
                title = finalrender.title_of(work, name)
                out = work_dir(work) / f"{title} v{finalrender.next_version(work, title)} (1080p).mp4"
                shutil.copyfile(watchnotes.preview_file(work, name), out)
                out.with_name(out.stem + ".final.json").write_text(json.dumps({"version": 1, "dur": 9.0}), encoding="utf-8")
                job["ok"] = True
                job["done"] = True
                return
            p = subprocess.Popen([str(PY), str(TOOLS / "finalrender.py"), "run", work, name], cwd=TOOLS, env=tool_env(), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                if line.startswith("STEP "):
                    try:
                        job["step"] = max(0, min(4, int(line.split()[1].split("/")[0]) - 2))
                    except ValueError:
                        pass
                if line.strip() and not line.lstrip().startswith(("[NeMo", "[W", "[I")):
                    job["log"] = (job["log"] + line)[-30000:]
            job["ok"] = p.wait() == 0
        except Exception as e:                     # noqa: BLE001 - report anything to the UI
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)

    threading.Thread(target=run, daemon=True).start()
    return job


def _job(pipeline, steps):
    if any(j.get("pipeline") and not j["done"] for j in _jobs.values()):
        raise ValueError("another job is running (render, analysis or Claude): wait for it to finish")
    job = {"id": uuid.uuid4().hex[:8], "pipeline": pipeline, "log": "", "done": False, "ok": None, "step": 0, "steps": steps, "out": None, "started": time.time()}
    _jobs[job["id"]] = job
    return job


def _job_run(job, cmds, after=None):
    """Run the commands one after another (job['step'] follows), stop at the first failure, keep the log tail; after() runs before the job is marked done."""
    def run():
        try:
            for i, (cmd, cwd) in enumerate(cmds):
                job["step"] = i
                p = subprocess.Popen(cmd, cwd=cwd, env=tool_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace")
                for line in p.stdout:
                    if line.strip() and not line.lstrip().startswith(("[NeMo", "[W", "[I", "frame=", "INFO:", "W0000", "WARNING:", "I0000")):
                        job["log"] = (job["log"] + line)[-30000:]
                job["ok"] = p.wait() == 0
                if not job["ok"]:
                    break
            if job["ok"] and after:
                after()
        except Exception as e:                     # noqa: BLE001 - report anything to the UI
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


SHORTS_V2_EDITS = {"keep": lambda b: {"id": b["id"], "status": "kept" if b.get("keep", True) else ""},
                   "drop": lambda b: {"id": b["id"], "status": "dropped" if b.get("drop", True) else ""},
                   "hook": lambda b: {"id": b["id"], "hook": str(b.get("hook", ""))[:90].upper()},
                   "title": lambda b: {"id": b["id"], "title": str(b.get("title", ""))[:90]},
                   "pace": lambda b: {"id": b["id"], "pace": b.get("pace", "")},
                   "style": lambda b: {"id": b["id"], "caption_style": b.get("style", "")},
                   "music": lambda b: {"id": b["id"], "music": b.get("music", "")},
                   "sfx": lambda b: {"id": b["id"], "sfx": b.get("sfx", "")},
                   "emphasis": lambda b: {"id": b["id"], "emphasis": b.get("words", [])}}


def shorts_v2_post(op, b):
    """The Shorts screen's actions. Quick edits answer with the project; long ones start a job and answer with its id."""
    def started(job, sentence, done=""):
        job["sentence"] = sentence
        if done:
            job["done_sentence"] = done
        return {"id": job["id"]}
    if op == "kit":                                            # which sound effects play each role, saved for this user
        import sfxkit
        with _lock:
            sfxkit.save_kit(b.get("roles") or {})
        return shortsview.sounds()
    if op in ("fromfile", "fromfolder"):
        if op == "fromfile":
            job = started(start_shorts_from_file(b["path"]), "Reading your video, then choosing shorts", "Shorts ready")
        else:
            job = started(start_shorts_from_folder(b["path"]), "Reading your recordings, then choosing a short", "Shorts ready")
        return {**job, "key": _jobs[job["id"]]["key"]}
    work, name = views.split_key(b["key"])
    sid = b.get("id", "")
    if op == "fromraw":                                        # a newer short from this video's raw footage, as its own project: the shorts made so far stay
        brief = shortsapp.raw_brief(work, name, sid, b.get("text", ""))
        job = started(start_shorts_from_folder(shortsapp.footage_folder(work, name), brief), "Reading your recordings, then telling the new story", "New short ready")
        return {**job, "key": _jobs[job["id"]]["key"]}
    if op in SHORTS_V2_EDITS:
        with _lock:
            shortsapp.apply_op(work, name, "edit", SHORTS_V2_EDITS[op](b))
        return shortsview.project(work, name)
    if op == "cut":
        with _lock:
            shortsapp.apply_op(work, name, "cut", {"id": sid, "start": b["start"], "end": b["end"], "cut": bool(b.get("cut", True))})
        return shortsview.words(work, name, sid)
    if op == "publish":                                        # the YouTube details of one short, edited by hand
        with _lock:
            shortsapp.apply_op(work, name, "publish", {"id": sid, **{k: b[k] for k in ("title", "description", "filename", "tags") if k in b}})
        return shortsview.project(work, name)
    if op == "link":                                           # the full video's address, put in the descriptions
        with _lock:
            shortsapp.apply_op(work, name, "project", {"full_video_url": b.get("url", "")})
        return shortsview.project(work, name)
    if op == "titles":                                         # Claude writes titles, descriptions, tags and file names
        raw = shortsapp.read_raw(work, name)
        ids = [sid] if sid else [x["id"] for x in shortsapp.live(raw.get("shorts", []))]
        return started(start_shorts_titles(work, name, ids), "Claude is writing the titles and descriptions", "Titles written")
    if op == "gfxplan":
        return started(start_shorts_gfxplan(work, name, sid), "Claude is planning the graphics of your short", "Graphics planned")
    if op == "gfxcut":                                         # a graphic is built unless the host cuts it
        with _lock:
            shortsapp.gfx_mark(work, name, sid, b["g"], "cut" if b.get("cut", True) else "", "")
        return shortsview.project(work, name)
    if op == "note":                                           # the host's feedback: a note on one short, or a general one when no short is named
        with _lock:
            shortsapp.add_feedback(work, name, sid, b.get("text", ""))
        return shortsview.project(work, name)
    if op == "noteedit":
        with _lock:
            shortsapp.edit_feedback(work, name, sid, b["note"], status=b.get("status"), delete=bool(b.get("delete")))
        return shortsview.project(work, name)
    if op == "feedback":                                       # Claude applies the open notes of one short
        return started(start_shorts_feedback(work, name, sid), "Claude is applying your feedback", "Feedback applied")
    if op == "preview":
        return started(start_shorts_render(work, name, sid), "Making the preview of your short", "Preview ready")
    if op == "tighten":
        return started(start_shorts_tighten(work, name, [sid]), "Claude is tightening your short", "Short tightened")
    if op == "make":                                           # the first time: read the final, then Claude chooses
        rec = shortsview.recommendation(work, name, (finalrender.finals(work, name) or [None])[0])
        return started(start_shorts_make(work, name, int(b.get("count") or rec["count"] or 3)), "Making your shorts", "Shorts ready")
    if op == "find":
        return started(start_shorts_find(work, name, int(b["count"]) if b.get("count") else None), "Claude is choosing shorts", "Shorts chosen")
    if op == "finish":
        return started(start_shorts_finish(work, name), "Making the final shorts", "Final shorts ready")
    raise ValueError("unknown action")


def start_shorts_render(work, name, sid):
    shortsapp.read_raw(work, name)
    job = _job("shorts", ["render the vertical preview (auto crops are worked out first the first time)"])
    return _job_run(job, [([str(PY), str(TOOLS / "shorts.py"), "render", str(shortsapp.cfg_file(work, name)), sid], TOOLS)])



def _claude_run(job, fd, prompt, out_name, apply, budget="1.5", kind="edit"):
    """One headless Claude run that reads and writes files only. `kind` picks the model and effort chosen in Settings (claudemodels). It must write `out_name` in folder `fd`; apply(path, result) -> (ok, message)
    is then called under the lock. Blocks until finished; sets job['log'] and job['ok'] but not job['done']."""
    import usage
    fd.mkdir(parents=True, exist_ok=True)
    out = fd / out_name
    if out.exists():
        out.unlink()
    (fd / "PROMPT.md").write_text(channel.prompt(prompt), encoding="utf-8")
    fake = os.environ.get("WOOTS_FAKE_CLAUDE")      # tests: copy a canned answer instead of calling claude
    if fake:
        src = Path(fake) / out_name
        if not src.is_file():
            job["log"] += f"fake claude has no {out_name}"
            job["ok"] = False
            return
        shutil.copyfile(src, out)
        with _lock:
            ok, msg = apply(out, {"total_cost_usd": 0})
        job["log"] += msg
        job["ok"] = ok
        return
    cmd = clauderun.command(builder.find_claude(), "Read,Write", ["Read", "Write"], claudemodels.budget(kind, budget), claudemodels.flags(kind))
    result = None
    try:
        p = clauderun.start(cmd, prompt, fd, tool_env())
        err = []
        threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True).start()
        for line in p.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "rate_limit_event":
                try:
                    usage.save_rate_limit(e.get("rate_limit_info") or {})
                except Exception:               # noqa: BLE001
                    pass
            elif e.get("type") == "result":
                result = e
        rc = p.wait()
        if rc == 0 and result and not result.get("is_error") and out.exists():
            with _lock:
                ok, msg = apply(out, result)
            job["log"] += msg + f" (cost ${result.get('total_cost_usd', 0):.2f})."
            job["ok"] = ok
        else:
            why = (result or {}).get("result") if (result or {}).get("is_error") else (result or {}).get("subtype")      # "OAuth session expired", not "success"
            if why and "budget" in str(why):
                why = "Claude ran out of budget for this step"
            job["log"] += (why or (err[0].strip()[-300:] if err and err[0] else f"exit {rc}")) + " (nothing was added)"
            job["ok"] = False
    except Exception as e:                      # noqa: BLE001
        job["log"] += f"\n{e}"
        job["ok"] = False


def _claude_find(job, work, name, count):
    """Claude reads the transcript and the beat map's visual moments and proposes `count` shorts."""
    prompt = shortsapp.find_prompt(work, name, count)

    def apply(path, result):
        n = shortsapp.import_candidates(work, name, path, count)
        skipped = (shortsapp.read_raw(work, name).get("last_find") or {}).get("skipped") or []
        return n > 0, (f"Claude proposed {n} short{'s' if n != 1 else ''}."
                       + (f" Left out because they broke the rules: {'; '.join(skipped)}." if skipped else ""))
    _claude_run(job, WORK / work / "shorts" / "_find", prompt, "candidates.json", apply, kind="shorts")


def start_make_version(work, name, stage):
    """v2 'Make cut N / preview N from my notes'. Exact clip choices (cut only) are applied by code; the free-text notes are applied by one
    headless Claude run; then the video is made (cut: the clips-only render; preview: rebuild what changed and stitch) and kept as the next version.
    Stop works between the parts. With WOOTS_FAKE_CLAUDE set the preview is not rebuilt (a copy stands in)."""
    import cutview
    import makeversion
    if stage not in ("cut", "preview"):
        raise ValueError("unknown step")
    first_cut = stage == "cut" and not reviewnotes.versions(work, name, "cut")
    plain = makeversion.plain_notes(work, name, stage)
    exact = [n for n in reviewnotes.open_notes(work, name, stage) if n not in plain]
    if not (plain or exact or first_cut):
        raise ValueError("add a note first")
    if stage == "preview":
        makeversion.ensure_baseline(work, name, stage)
    job = _job(stage, ["apply the notes", "make the video", "keep it"])
    job.update(work=work, name=name, stage=stage)
    fd = WORK / work / "v2-run" / stage
    result = {"applied_ids": [], "changes": []}

    def apply(path, res):
        ok, msg, r = makeversion.apply_answer(work, name, stage, path)
        if ok:
            result["applied_ids"] += r["applied_ids"]
            result["changes"] += r["changes"]
            result["lesson"] = r.get("lesson", "")
        return ok, msg

    def run():
        try:
            job["ok"] = True
            if stage == "cut" and exact:
                with _lock:
                    r = cutview.apply_choices(work, name)
                result["applied_ids"] += r["applied_ids"]
                result["changes"] += r["changes"]
            if plain:
                _claude_run(job, fd, makeversion.brief(work, name, stage, fd), "answer.json", apply, budget="1.0")
                if not job["ok"] and result["applied_ids"]:
                    job["ok"] = True                    # the exact choices were applied: go on without the free-text notes
            if job["ok"] and not job.get("stop"):
                job["step"] = 1
                if stage == "cut":
                    video, rows = cutview.render(work, name)
                elif os.environ.get("WOOTS_FAKE_CLAUDE"):
                    makeversion.fake_stitch(work, name)
                else:
                    builder.start(work, name)
                    while not job.get("stop"):
                        st = builder.state(work, name)
                        if not st["running"] and not st["queued"]:
                            break
                        time.sleep(2)
                    if job.get("stop"):
                        for s in builder.state(work, name)["sections"]:
                            if s["status"] in ("queued", "running"):
                                builder.cancel(work, name, s["id"])
                        job["ok"] = False
                    else:
                        job["step"] = 2
                        builder.stitch(work, name)
            if job["ok"] and not job.get("stop"):
                job["step"] = 2
                v = (makeversion.finish_cut(work, name, video, rows, result) if stage == "cut" else makeversion.finish(work, name, stage, result))
                job["log"] += f" Kept as {reviewnotes.label(stage, v['n'])}."
            elif job.get("stop"):
                job["ok"] = False
                job["log"] += " Stopped."
        except Exception as e:                      # noqa: BLE001 - report anything to the UI
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_rough_cut(work, name):
    """The Footage step's one button: read any recordings not read yet, look at all the footage, match the takes to the outline, build the beat map,
    find footage for the shot ideas, then cut the clips together and keep it as the next cut. Each part is skipped when it is already done."""
    import brolllib
    import cutview
    import footageview
    import makeversion
    rec = footageview.recordings(work, name)
    if not rec["folder"]:
        raise ValueError("choose the folder you recorded into first")
    has_outline = bool(outline.load(work, name)["sections"])
    if not has_outline and not rec["total"]:
        raise ValueError("write the outline first")                     # nothing recorded to write one from
    recut.reload_rules()                            # the numbers come from the youtube-edit skill: a change there shows in the next cut
    coldopen.reload_rules()
    framing.reload_rules()
    job = _job("cut", ["read the recordings", "look at the footage", "match the clips to the outline", "cut them together"])
    job.update(work=work, name=name, stage="cut")
    fake = bool(os.environ.get("WOOTS_FAKE_CLAUDE"))

    def fail(msg):
        job["log"] += msg
        job["ok"] = False

    def run():
        import hashlib
        skipped = []

        def claude_step(label, *a, **kw):                      # a step that fails does not stop the cut, but the host is told it was not done
            n = len(job["log"])
            _claude_run(job, *a, **kw)
            if not job.get("ok"):
                skipped.append(f"Not done: {label} ({job['log'][n:].strip()[:140] or 'it did not finish'})")
            job["ok"] = True
        try:
            job["ok"] = True
            if rec["unread_refs"] and not fake:
                paths = [(rel, footage_path_ok(work, name, rel)) for rel in rec["unread_refs"]]
                tdir = work_dir(work) / "footage"
                tdir.mkdir(exist_ok=True)
                items = [{"src": str(p), "out": str(tdir / (hashlib.sha1(rel.encode()).hexdigest()[:10] + ".transcript.json"))} for rel, p in paths]
                man = tdir / "analyze.manifest.json"
                man.write_text(json.dumps(items), encoding="utf-8")
                if not _transcribe(job, work, name, paths, items, man):
                    return fail("\nreading the recordings failed")
            if job.get("stop"):
                return fail(" Stopped.")
            if not has_outline:                                                   # no outline: Claude writes one from what was recorded (C2)
                import story
                fd = WORK / work / "v2-run" / "outline"
                _claude_run(job, fd, story.outline_from_recordings(work, name, fd), "outline.md", lambda p, r: outline.apply_answer(work, name, p), budget="1.2", kind="story")
                if not outline.load(work, name)["sections"]:
                    return fail(" write the outline first: Claude could not write one from your recordings")
                job["ok"] = True
            job["step"] = 1
            if not brolllib.state(work, name)["ready"] and not _look_at_footage(job, work, name):
                return fail("\nlooking at the footage failed")
            if job.get("stop"):
                return fail(" Stopped.")
            job["step"] = 2
            with _lock:
                clipmap.build(work, name)                          # the per-line takes stay for "other takes" and the line view
                built = recut.build_beats(work, name)              # the cut itself: whole recordings in outline order, mistakes taken out (ADR 0009)
                found = shotmatch.match(work, name)
            if takes.load(work, name).get("v") != takes.VERSION:                # passages said more than once: the best take stays, the others become options
                fd = WORK / work / "v2-run" / "takes"
                claude_step("comparing takes of the same passage", fd, takes.brief(work, name, fd), "takes.json", lambda p, r: takes.apply_review(work, name, p), budget="0.6", kind="story")
                job["ok"] = True                       # without the read both takes stay in the cut
            import story
            if story.load(work, name).get("v") != story.VERSION:               # the story of the recordings, once per set of recordings: the cold open and the cut read use it
                fd = WORK / work / "v2-run" / "story"
                claude_step("finding the story in your recordings", fd, story.brief(work, name, fd), "story.json", lambda p, r: story.apply_answer(work, name, p), budget="0.8", kind="story")
            with _lock:
                other_takes = cutreview.apply(work, name, recut.MAX_PAUSE_S, recut.SILENCE_PAD_S, recut.SILENCE_LEAD_S, takes.drops(work, name), takes.restores(work, name))
                held_back = list(cutreview.LOCKED_SKIPPED)
            if not coldopen.load(work, name).get("options") and not coldopen.load(work, name).get("skip"):
                fd = WORK / work / "v2-run" / "coldopen"
                claude_step("looking for a cold open", fd, coldopen.brief(work, name, fd), "hooks.json", lambda p, r: coldopen.apply_options(work, name, p), budget="0.6", kind="story")
                job["ok"] = True                       # no cold open is fine: the cut still starts with the intro
            with _lock:
                coldopen.insert(work, name)
            if cutreview.load(work, name).get("v") != cutreview.VERSION:         # the read of the cut comes after the cold open: the opening must fit the hook budget
                fd = WORK / work / "v2-run" / "cutreview"
                claude_step("reading the cut for repeats and contradictions", fd, cutreview.brief(work, name, fd), "review.json", lambda p, r: cutreview.apply_review(work, name, p), budget="0.6", kind="story")
                job["ok"] = True                       # a cut nobody read is still a cut
            with _lock:
                dropped = cutreview.apply(work, name, recut.MAX_PAUSE_S, recut.SILENCE_PAD_S, recut.SILENCE_LEAD_S)
                held_back += [d for d in cutreview.LOCKED_SKIPPED if d not in held_back]
            if shotmatch.ambiguous(work, name):
                fd = WORK / work / "v2-run" / "shots"
                claude_step("choosing between footage for the shots", fd, shotmatch.pick_brief(work, name, fd), "picks.json", lambda p, r: shotmatch.apply_picks(work, name, p), budget="0.6")
                job["ok"] = True                       # the first choice stands when Claude could not choose
            with _lock:
                recut.place_broll(work, name, shotmatch.load(work, name), shotmatch.plan(work, name))
                recut.cover_with_footage(work, name)
                recut.cover_by_name(work, name)
                wrong = recut.audit_cutaways(work, name)
            lack = framing.missing(work, name, clipmap.read_json(beatmap.path_of(work, name), {"beats": []}))
            if lack:
                fd = WORK / work / "v2-run" / "framing"
                cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
                claude_step("finding where the eyes are for punch-ins", fd, framing.brief(work, name, cfg.get("folder", ""), lack, fd), "framing.json", lambda p, r: framing.apply_answer(work, name, p, fd), budget="0.4")
                job["ok"] = True                       # no zoom is made where the eyes are not known
            try:                                       # where the face is across the picture: a punch-in is centered on it (the creator 2026-10-29)
                framing.find_faces(work, name, (clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}).get("folder", ""),
                                   framing.talking_recordings(clipmap.read_json(beatmap.path_of(work, name), {"beats": []})))
            except Exception as e:                      # noqa: BLE001 - without it the crop stays on the middle
                job["log"] += f" (face position not measured: {e})"
            with _lock:
                zoomed = framing.apply_zoom(work, name)
            if job.get("stop"):
                return fail(" Stopped.")
            job["step"] = 3
            video, rows = cutview.render(work, name)
            left = [Path(x["rel"]).stem for x in built["left_out"] if "earlier take" in x["why"] or "said again" in x["why"]]
            changes = [*skipped, f"Cut {len(built['recordings'])} recordings together in outline order", f"{found['ready']} of {found['total']} shots have footage"]
            if left:
                changes.append("Left out earlier takes of: " + ", ".join(left))
            for g in takes.load(work, name).get("groups", []):
                changes.append(f"Said more than once: \"{g['topic']}\" ({len(g['takes'])} takes, take {g['best'] + 1} used)")
            if coldopen.load(work, name).get("skip"):
                changes.append(f"No cold open: {coldopen.load(work, name).get('why') or 'the opening already hooks'}")
            for d in [x for x in other_takes if x["kind"] != "other-take"] + dropped:
                changes.append(f"Took out ({d['kind']}):\"{d['text'][:70]}\" - {d['why']}")
            for d in held_back:
                changes.append(f"Locked, not changed: \"{d['text'][:70]}\" (a good moment to keep; the rules wanted it out: {d.get('why') or d.get('kind', '')})")
            for c in cutreview.load(work, name).get("checks", []):
                changes.append(f"Check the fact: \"{c['text'][:70]}\" - {c['why']}")
            for s in cutreview.load(work, name).get("suggestions", []):
                changes.append(f"Suggestion, not done: move \"{s['text'][:70]}\" before \"{s['before'][:50]}\" - {s['why']}")
            if zoomed:
                changes.append(f"{zoomed} punch-in zoom{'' if zoomed == 1 else 's'} on the talking head, eyes kept on one line")
            if wrong:
                changes.append(f"{len(wrong)} cutaway{'' if len(wrong) == 1 else 's'} of another program taken out")
            if found["nothing"]:
                one = found["nothing"] == 1
                changes.append(f"{found['nothing']} shot{'' if one else 's'} still {'has' if one else 'have'} nothing")
            for b in clipmap.read_json(beatmap.path_of(work, name), {"beats": []})["beats"]:      # why each cutaway was chosen (the creator 2026-10-29: "why was that one chosen?")
                for x in (b.get("on_screen") or {}).get("broll", []):
                    if x.get("file"):
                        t = float(b.get("start", 0)) + float(x.get("at", 0))
                        changes.append(f"Cutaway at {int(t // 60)}:{int(t % 60):02d} over \"{b.get('said', '')[:50]}\": {Path(x['file']).stem} - {str(x.get('why') or 'picked by Claude from the shot list')[:140]}")
            try:
                import cutcheck
                kept = cutcheck.run(work, name, str(video))
                failing = [f"{r['rule']} ({r['value']}{' at ' + ', '.join(map(str, r['where'][:3])) if r['where'] else ''})" for r in kept if not r["ok"]]
                changes.append(f"Rule check: {len(kept) - len(failing)} of {len(kept)} rules of the skill kept" + (". Not kept: " + "; ".join(failing) if failing else ""))
            except Exception as e:                      # the check is a report, never a reason to lose the cut
                changes.append(f"Rule check could not run: {e}")
            import story
            v = makeversion.finish_cut(work, name, video, rows, {"changes": changes, "applied_ids": [], "suggestions": story.note_suggestions(work, name)})
            job["log"] += f" Kept as {reviewnotes.label('cut', v['n'])}."
        except Exception as e:                      # noqa: BLE001 - report anything to the UI
            fail(f"\n{e}")
        finally:
            job["done"] = True
            job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_score(work, name):
    """Measure the latest final against the reference videos (scorecard.py)."""
    job = _job("score", ["measure the final against the reference videos"])
    job.update(work=work, name=name)
    return _job_run(job, [([str(PY), str(TOOLS / "scorecard.py"), "run", work, name], TOOLS)])


def start_vision(work, name):
    """Look at all the footage that has not been looked at yet (no transcription): what is on screen, for clips with no speech."""
    job = _job("vision", ["look at the footage (vision model; clips already looked at are skipped)"])
    job.update(work=work, name=name)
    return _job_run(job, [([str(PY), str(TOOLS / "brolllib.py"), work, "--name", name], TOOLS)])


def start_find_options(work, name, ref):
    """Claude searches every recording for other takes of one clip's line (slower and costs a little; used when there are fewer than 2 others)."""
    import cutview
    job = _job("options", ["Claude reads the recordings"])
    job.update(work=work, name=name)
    fd = WORK / work / "v2-run" / "options"
    prompt = cutview.search_prompt(work, name, ref, fd)

    def run():
        _claude_run(job, fd, prompt, "options.json", lambda p, r: cutview.import_found(work, name, ref, p), budget="0.8")
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_outline(work, name, note=""):
    """Claude drafts the outline (none yet) or revises it for the creator's note. The old text is kept as a saved version (scriptedit._write)."""
    job = _job("outline", ["Claude writes the outline"])
    job.update(work=work, name=name)
    fd = WORK / work / "v2-run" / "outline"
    prompt = outline.brief(work, name, fd, note)

    def run():
        _claude_run(job, fd, prompt, "outline.md", lambda p, r: outline.apply_answer(work, name, p), budget="1.2", kind="story")
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_publish(work, name, note=""):
    """Claude writes (or redoes, with the creator's note) the titles, description, tags and thumbnail prompts. A small run: it changes nothing else."""
    job = _job("publish", ["Claude writes the publishing details"])
    job.update(work=work, name=name)
    fd = WORK / work / "v2-run" / "publish"
    prompt = publish.brief(work, name, fd, note)

    def run():
        _claude_run(job, fd, prompt, "publish.json", lambda p, r: publish.apply_answer(work, name, p), budget="0.8", kind="story")
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_archive(work, name, title, project):
    """Save the project bundle into the footage folder, move the final there, delete the regenerable files. Permanent: the caller confirmed."""
    import archive
    job = _job("archive", ["save the project next to the footage", "move the final and clean up"])
    job.update(work=work, name=name)

    def run():
        try:
            with _lock:
                r = archive.run(work, name, title, project)
            job["log"] += f"Saved {r['bundle']['files']} files and freed {r['bytes_freed'] // 2**20} MB."
            job["ok"] = True
        except Exception as e:                      # noqa: BLE001 - report anything to the UI; nothing is deleted before the bundle is written
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_find_teaching(work, name):
    """Claude reads what the creator says in each clip and suggests more terms a newcomer needs explained (a small run; changes no plan but teaching.json)."""
    job = _job("teaching", ["Claude reads the clips"])
    job.update(work=work, name=name)

    def run():
        fd = WORK / work / "v2-run" / "teaching"
        _claude_run(job, fd, teaching.find_prompt(work, name, fd), "teaching.json", lambda p, r: teaching.import_found(work, name, p), budget="0.6")
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_shorts_gfxplan(work, name, sid):
    """Claude plans the graphics of ONE short (where each goes, what it is): a small run; nothing is built."""
    raw = shortsapp.read_raw(work, name)
    short = next((s for s in raw.get("shorts", []) if s["id"] == sid), None)
    if not short:
        raise ValueError(f"no short {sid!r}")
    prompt = shortsapp.gfx_prompt(work, name, sid)
    job = _job("shorts", [f"Claude plans the graphics for {sid.upper()}"])

    def apply(path, result):
        r = shortsapp.gfx_import(work, name, sid, path)
        return r["added"] > 0, (f"Claude planned {r['added']} graphic{'s' if r['added'] != 1 else ''} for {sid.upper()}."
                                + (f" Left out: {'; '.join(r['skipped'])}." if r["skipped"] else ""))

    def run():
        _claude_run(job, WORK / work / "shorts" / "_gfx" / sid, prompt, "graphics.json", apply, budget="0.6", kind="shorts")
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_shorts_find(work, name, count=None):
    shortsapp.read_raw(work, name)
    job = _job("shorts", ["Claude chooses the shorts"])

    def run():
        _claude_find(job, work, name, count)
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_shorts_make(work, name, count):
    """'Go': make `count` shorts from this video's own final render. First time: transcribe the final and write <name>.shorts.json;
    then Claude chooses the shorts. The count is the recommendation, or whatever the creator asked for."""
    if not isinstance(count, int) or not 1 <= count <= shortsplan.hard_cap() + 2:
        raise ValueError(f"ask for between 1 and {shortsplan.hard_cap() + 2} shorts")
    steps = ["Claude chooses the shorts"]
    if shortsapp.cfg_file(work, name).exists():
        job = _job("shorts", steps)
        job["ok"] = True
        return _job_run(job, [], lambda: _claude_find(job, work, name, count))
    finals = finalrender.finals(work, name)
    if not finals:
        raise ValueError("render the final first (Final tab): shorts are cut from the final video")
    src = WORK / work / finals[0]["file"]
    wd = WORK / work
    tr = wd / f"{src.stem}.transcript.json"
    job = _job("shorts", ["transcribe the final video (Parakeet)", "write the shorts project"] + steps)

    def after():
        job["step"] = 1
        with _lock:
            shortsapp.new_project(work, name, str(src).replace("\\", "/"), str(tr).replace("\\", "/"), None)
        job["step"] = 2
        _claude_find(job, work, name, count)
    return _job_run(job, [([str(PY), str(TOOLS / "transcribe.py"), str(src), "--out", str(wd)], TOOLS)], after)


def start_shorts_from_file(path):
    """Shorts from any finished video file: the file stays where it is. Read it word by word, write a project in its own work folder, then Claude chooses.
    Returns the job and the video's key."""
    src = Path(path)
    if not src.is_file() or src.suffix.lower() not in footage_cfg.VIDEO_EXT:
        raise ValueError("pick a video file")
    work, name = shortsapp.standalone_names(src)
    wd = WORK / work
    wd.mkdir(parents=True, exist_ok=True)
    tr = wd / f"{src.stem}.transcript.json"
    job = _job("shorts", ["read the video word by word", "write the shorts project", "Claude chooses the shorts"])
    job["key"] = views.key_of(work, name)

    def after():
        job["step"] = 1
        with _lock:
            shortsapp.new_project(work, name, str(src).replace("\\", "/"), str(tr).replace("\\", "/"), None)
        job["step"] = 2
        _claude_find(job, work, name, shortsapp.video_plan(work, name)["recommended"] or 3)
    return _job_run(job, [([str(PY), str(TOOLS / "transcribe.py"), str(src), "--out", str(wd)], TOOLS)], after)


def start_shorts_from_folder(path, brief=""):
    """A short from a folder of raw footage: read every recording that has sound word by word, tell the talking ones from the b-roll, write the project
    (the files stay where they are), then Claude chooses. Returns the job; job['key'] is the project's key."""
    import rawshorts
    folder = Path(path)
    files = rawshorts.scan(folder)
    if not files:
        raise ValueError("there are no video files in that folder")
    work, name = shortsapp.standalone_names(folder)
    wd = WORK / work
    wd.mkdir(parents=True, exist_ok=True)
    job = _job("shorts", ["read the recordings word by word", "tell the talking from the b-roll, write the project", "Claude chooses the shorts"])
    job["key"] = views.key_of(work, name)
    todo = [f for f in files if shortsapp.sh.has_audio(f)]

    def after():
        job["step"] = 1
        info = rawshorts.tell_apart(files, wd)
        with _lock:
            rawshorts.new_project(work, name, folder, info, brief)
        job["step"] = 2
        _claude_find(job, work, name, skillrules.shorts()["raw_max_shorts"])
    cmds = [([str(PY), str(TOOLS / "transcribe.py"), *map(str, todo), "--out", str(wd)], TOOLS)] if todo else []
    return _job_run(job, cmds, after)


def start_shorts_feedback(work, name, sid):
    """Claude changes one short to meet the host's open notes on it (cuts, hook, title); the notes are then marked done. Afterwards the short is measured
    (how much of it is still spoken over the host's face) so the result says so."""
    raw = shortsapp.read_raw(work, name)
    if not any(x["id"] == sid for x in raw.get("shorts", [])):
        raise ValueError("no such short")
    if not shortsapp.open_feedback(raw, sid):
        raise ValueError("write some feedback on this short first")
    job = _job("shorts", [f"Claude applies your feedback to {sid.upper()}"])

    def apply(path, result):
        r = shortsapp.apply_feedback(work, name, sid, path)
        bits = [x for x, on in (("cuts", r["changed_cuts"]), ("the hook", r["hook"]), ("the title", r["title"])) if on]
        return True, (f"{sid.upper()}: changed {' and '.join(bits)}." + (f" Not done: {'; '.join(r['unmet'])}." if r["unmet"] else ""))

    def run():
        try:
            prompt = shortsapp.feedback_prompt(work, name, sid)         # looks at the video to find where the face is on screen: a few seconds, outside the lock
            _claude_run(job, WORK / work / "shorts" / "_feedback" / sid, prompt, "tighten.json", apply, budget="1.0", kind="shorts")
            if job.get("ok"):
                face = shortsapp.record_face_share(work, name, sid)
                if face is not None:
                    job["log"] += f" About {round(face * 100)}% of the words are still spoken over your face."
        except Exception as e:                  # noqa: BLE001
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_shorts_tighten(work, name, ids):
    """Claude cuts content out of each short (filler, tangents, repeats, slow set-ups) so it is dense; one headless run per short, one after another."""
    import usage
    raw = shortsapp.read_raw(work, name)
    ids = [i for i in ids if any(x["id"] == i for x in raw.get("shorts", []))]
    if not ids:
        raise ValueError("no such short")
    job = _job("shorts", [f"Claude tightens {i.upper()}" for i in ids])

    def one(sid):
        fd = WORK / work / "shorts" / "_tighten" / sid
        fd.mkdir(parents=True, exist_ok=True)
        out = fd / "tighten.json"
        if out.exists():
            out.unlink()
        prompt = shortsapp.tighten_prompt(work, name, sid)
        (fd / "PROMPT.md").write_text(channel.prompt(prompt), encoding="utf-8")
        cmd = clauderun.command(builder.find_claude(), "Read,Write", ["Read", "Write"], claudemodels.budget("shorts", "1.0"), claudemodels.flags("shorts"))
        p = clauderun.start(cmd, prompt, fd, tool_env())
        err, result = [], None
        threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True).start()
        for line in p.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "rate_limit_event":
                try:
                    usage.save_rate_limit(e.get("rate_limit_info") or {})
                except Exception:                   # noqa: BLE001
                    pass
            elif e.get("type") == "result":
                result = e
        rc = p.wait()
        if rc == 0 and result and not result.get("is_error") and out.exists():
            with _lock:
                r = shortsapp.apply_tighten(work, name, sid, out)
            return f"{sid.upper()}: kept {r['words']} words (about {r['speech']} s of speech), ${result.get('total_cost_usd', 0):.2f}"
        raise ValueError(((result or {}).get("subtype") or (err[0].strip()[-200:] if err and err[0] else f"exit {rc}")))

    def run():
        done, bad = [], []
        for k, sid in enumerate(ids):
            job["step"] = k
            try:
                done.append(one(sid))
            except Exception as e:                  # noqa: BLE001
                bad.append(f"{sid.upper()}: {e}")
            job["log"] = "\n".join(done + bad)
        job["ok"] = bool(done)
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def _claude_json_run(fd, prompt, out_name, budget="1.0"):
    """One headless Claude run in folder fd that must write out_name there; returns (ok, result_event, error_text)."""
    import usage
    out = fd / out_name
    if out.exists():
        out.unlink()
    (fd / "PROMPT.md").write_text(channel.prompt(prompt), encoding="utf-8")
    cmd = clauderun.command(builder.find_claude(), "Read,Write", ["Read", "Write"], claudemodels.budget("shorts", budget), claudemodels.flags("shorts"))
    p = clauderun.start(cmd, prompt, fd, tool_env())
    err, result = [], None
    threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True).start()
    for line in p.stdout:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "rate_limit_event":
            try:
                usage.save_rate_limit(e.get("rate_limit_info") or {})
            except Exception:                       # noqa: BLE001
                pass
        elif e.get("type") == "result":
            result = e
    rc = p.wait()
    ok = rc == 0 and result and not result.get("is_error") and out.exists()
    return bool(ok), result, ((result or {}).get("subtype") or (err[0].strip()[-200:] if err and err[0] else f"exit {rc}"))


def start_shorts_titles(work, name, ids):
    """Claude writes the YouTube title, description, tags and a search-friendly file name for the given shorts (one run for all of them)."""
    raw = shortsapp.read_raw(work, name)
    ids = [i for i in ids if any(x["id"] == i for x in raw.get("shorts", []))]
    if not ids:
        raise ValueError("no shorts to write titles for")
    job = _job("shorts", ["Claude writes titles, descriptions and tags"])
    fd = WORK / work / "shorts" / "_publish"
    fd.mkdir(parents=True, exist_ok=True)
    prompt = shortsapp.publish_prompt(work, name, ids)

    def run():
        try:
            ok, result, err = _claude_json_run(fd, prompt, "publish.json", "1.0")
            if ok:
                with _lock:
                    n = shortsapp.apply_publish(work, name, fd / "publish.json")
                job["log"] = f"Titles and descriptions written for {n} short{'s' if n != 1 else ''} (cost ${result.get('total_cost_usd', 0):.2f})."
                job["ok"] = n > 0
            else:
                job["log"] = err + " (nothing was changed)"
                job["ok"] = False
        except Exception as e:                      # noqa: BLE001
            job["log"] += f"\n{e}"
            job["ok"] = False
        job["done"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
    threading.Thread(target=run, daemon=True).start()
    return job


def start_shorts_finish(work, name):
    """Every short that is not dropped: render each at final quality (1080x1920, best encoder setting) unless it is already current, then copy them with their
    generated names into the finished video's own Shorts folder (never overwriting)."""
    raw = shortsapp.read_raw(work, name)
    wd = WORK / work
    kept = shortsapp.live(raw.get("shorts", []))
    if not kept:
        raise ValueError("no shorts to finish: every short is dropped")
    todo = []
    for s in kept:
        info = shortsapp._render_one(wd, s, ".final")
        if not info.get("exists") or info.get("stale"):
            todo.append(s["id"])
    job = _job("shorts", [f"final render {i.upper()}" for i in todo] + ["save into the video's Shorts folder"])
    if not todo:
        job["ok"] = True
    cmds = [([str(PY), str(TOOLS / "shorts.py"), "render", str(shortsapp.cfg_file(work, name)), sid, "--quality", "final"], TOOLS) for sid in todo]

    def after():
        job["step"] = len(todo)
        lines = []
        with _lock:
            shortsapp.deliver(work, name, log=lines.append)
        job["log"] = (job["log"] + "\n" if job["log"] else "") + "\n".join(lines)
    return _job_run(job, cmds, after)



# ----------------------------------------------------------------------------- HTTP
class TooBig(Exception):
    pass


def check_names(d):
    """Every video name a request carries (work, name, or key = work~name) must be one plain folder name: nothing here reaches a path unchecked."""
    if not isinstance(d, dict):
        return
    for k in ("work", "name"):
        if d.get(k) is not None:
            config.safe_part(d[k])
    if d.get("key") is not None:
        work, _, name = str(d["key"]).partition("~")
        config.safe_part(work)
        config.safe_part(name)


MEDIA_PREFIXES = {"/shortmedia/": 1, "/media/": 1}      # how many leading path parts are video names


def check_path_names(path: str):
    for prefix, n in MEDIA_PREFIXES.items():
        if path.startswith(prefix):
            for part in unquote(path[len(prefix):]).split("/")[:n]:
                config.safe_part(part)


class Handler(BaseHTTPRequestHandler):
    server_version = "WootsEditor/" + __import__("version").__version__

    def log_message(self, fmt_, *args):
        if "/media/" not in self.path:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt_ % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_header(self, keyword, value):
        super().send_header(keyword, value)
        if keyword.lower() == "content-type" and str(value).startswith("text/html"):
            self._html = True

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "_html", False):
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
                                                         "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        super().end_headers()

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > guard.MAX_BODY:
            raise TooBig()
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _refuse_or_none(self, method) -> bool:
        """True (after answering) when the guard refuses this request."""
        ok, status, why = guard.allowed(method, self.headers, self.client_address[0], self.server.server_address[1])
        if not ok:
            self.send_json({"error": why}, status)
        return not ok

    def _fail(self, e):
        sys.stderr.write("".join(traceback.format_exception(e)))
        try:
            self.send_json({"error": "Something went wrong.", "details": f"{type(e).__name__}: {e}"[:300]}, 500)
        except OSError:
            pass

    def do_GET(self):
        if self._refuse_or_none("GET"):
            return
        try:
            return self._route_get()
        except (ConnectionError, BrokenPipeError):
            return
        except Exception as e:                      # noqa: BLE001 - answered as a plain error instead of a dropped connection
            return self._fail(e)

    def do_POST(self):
        if self._refuse_or_none("POST"):
            return
        try:
            return self._route_post()
        except TooBig:
            return self.send_json({"error": "That request is too big."}, 413)
        except (ConnectionError, BrokenPipeError):
            return
        except Exception as e:                      # noqa: BLE001
            return self._fail(e)

    def _route_get(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            check_names(q)
            check_path_names(u.path)
            if u.path in ("/", "/index.html", "/v2"):
                self.send_response(302)
                self.send_header("Location", "/v2/")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if u.path == "/v2/":
                return self.send_file(STATIC / "v2" / "index.html")
            if u.path == "/api/v2/home":
                return self.send_json(views.home(list(_jobs.values())))
            if u.path == "/api/v2/settings":
                import appsetup
                return self.send_json(appsetup.view())
            if u.path == "/api/v2/engines":
                import engines
                return self.send_json(engines.view())
            if u.path == "/api/v2/claude-models":
                return self.send_json(claudemodels.view())
            if u.path == "/api/v2/channel":
                return self.send_json(channel.view())
            if u.path == "/api/v2/fonts":
                import sysfonts
                return self.send_json({"fonts": sysfonts.installed()})
            if u.path == "/api/v2/computer":
                import appsetup
                return self.send_json({"rows": appsetup.computer_check(), "graphics": appsetup.graphics_tool()})
            if u.path == "/api/v2/claude":
                import appsetup
                return self.send_json(appsetup.claude_status())
            if u.path == "/api/v2/job":
                js =[j for j in _jobs.values() if j.get("pipeline")]
                last = js[-1] if js else None
                return self.send_json({"job": {**views.job_sentence(last), "id": last["id"]} if last and not last["done"] else None,
                                       "last": {**views.job_sentence(last), "id": last["id"], "work": last.get("work"), "name": last.get("name")} if last else None})
            if u.path == "/api/v2/review":
                work, name = views.split_key(q["key"])
                return self.send_json(views.review(work, name, q["stage"], int(q["v"]) if q.get("v") else None, bool(_busy())))
            if u.path == "/api/v2/options":
                import cutview
                work, name = views.split_key(q["key"])
                found = cutview.options(work, name, q["clip"])
                return self.send_json({"can_search": len(found) < 2, "picture": not cutview.has_take(work, name, q["clip"]), "vision": cutview.vision_status(work, name), "options": [{**o, "frame": f"/api/v2/sourceframe?key={quote(q['key'])}&rel={quote(o['rel'])}&t={o['start'] + 0.5:.1f}",
                                                    "video": f"/api/v2/source?key={quote(q['key'])}&rel={quote(o['rel'])}", "at": views.time_text(o["start"])}
                                                   for o in found]})
            if u.path == "/api/v2/sourceframe":
                work, name = views.split_key(q["key"])
                return self.send_file(views.source_frame(work, name, q["rel"], float(q["t"])))
            if u.path == "/api/v2/source":
                work, name = views.split_key(q["key"])
                return self.send_file(views.source_path(work, name, q["rel"]), ranged=True)
            if u.path == "/api/v2/footage":
                work, name = views.split_key(q["key"])
                reading = any(j.get("pipeline") == "analyze" and not j["done"] and j.get("work") == work for j in _jobs.values())
                return self.send_json(views.footage_view(work, name, bool(_busy()), reading))
            if u.path == "/api/v2/locks":
                work, name = views.split_key(q["key"])
                return self.send_json(views.lock_view(work, name))
            if u.path == "/api/v2/tags":
                import tags
                work, name = views.split_key(q["key"])
                return self.send_json({"tags": tags.load(work, name)})
            if u.path == "/api/v2/clipframe":
                work, name = views.split_key(q["key"])
                return self.send_file(views.source_frame(work, name, q["rel"], float(q.get("t", 1))))
            if u.path == "/api/v2/outline":
                work, name = views.split_key(q["key"])
                return self.send_json(views.outline_view(work, name, bool(_busy())))
            if u.path == "/api/v2/final":
                work, name = views.split_key(q["key"])
                return self.send_json(views.final(work, name, bool(_busy())))
            if u.path == "/api/v2/thumbdraft":
                work, name = views.split_key(q["key"])
                return self.send_file(work_dir(work) / "final" / "thumbnail-draft.jpg")
            if u.path == "/api/v2/archive/preview":
                import archive
                import shootplan
                work, name = views.split_key(q["key"])
                folder, _ = shootplan.footage_folder(work, name)
                title = publish.load(work, name)["title"]
                if not title or not folder:
                    raise ValueError("choose the title and the footage folder first")
                return self.send_json(archive.preview(work, name, title, folder))
            if u.path == "/api/v2/frame":
                work, name = views.split_key(q["key"])
                return self.send_file(views.frame_path(work, q["file"], float(q["t"])))
            if u.path == "/api/v2/shorts/list":
                return self.send_json(shortsview.area())
            if u.path == "/api/v2/shorts":
                work, name = views.split_key(q["key"])
                return self.send_json(shortsview.project(work, name, bool(_busy())))
            if u.path == "/api/v2/shorts/sounds":
                return self.send_json(shortsview.sounds())
            if u.path == "/api/v2/shorts/words":
                work, name = views.split_key(q["key"])
                return self.send_json(shortsview.words(work, name, q["id"]))
            if u.path == "/api/v2/video":
                work, name = views.split_key(q["key"])
                f = views.facts(work, name)
                running = next((j for j in reversed(list(_jobs.values())) if j.get("pipeline") and not j["done"]), None)
                return self.send_json({"key": q["key"], "title": f["title"], **views.step_of(f, running if running and (running.get("work"), running.get("name")) == (work, name) else None)})
            if u.path == "/api/v2/thumb":
                work, name = views.split_key(q["key"])
                tp = usage.thumb_path(work, name)
                return self.send_file(tp) if tp else self.send_error(404)
            if u.path.startswith("/static/"):
                p = STATIC / unquote(u.path[len("/static/"):])
                if not config.inside(STATIC, p):
                    return self.send_error(404)
                return self.send_file(p)
            if u.path == "/api/code":
                return self.send_json({"stale": _code_newest() > _STARTED + 1, "boot": _STARTED, "static": _static_newest(), "busy": _busy(),
                                       "supervised": bool(os.environ.get("WOOTS_SUPERVISED"))})
            if u.path == "/api/accuracy":
                return self.send_json(accuracy.state(q["work"], q["name"]))
            if u.path == "/api/music":
                return self.send_json(musicaudition.state(q["work"], q["name"]))
            if u.path == "/api/resolve":
                return self.send_json(resolve_export.state(q["work"], q["name"]))
            if u.path == "/api/usage/week":
                return self.send_json(usage.week_summary())
            if u.path == "/api/usage":
                return self.send_json({"video": usage.video(q["work"], q["name"]), "all": usage.all_videos()})
            if u.path == "/api/history":
                return self.send_json({"entries": projectstore.history(work_dir(q["work"]), q.get("file"), int(q.get("limit", 60)))})
            if u.path == "/api/history/diff":
                return self.send_json(projectstore.diff(work_dir(q["work"]), q["id"], q.get("other")))
            if u.path == "/api/dash":
                return self.send_json(usage.cards())
            if u.path == "/api/fs":
                return self.send_json(list_dir(q.get("path", ""), files=q.get("files") == "1"))
            if u.path == "/api/shorts/frame":
                body = shortsapp.frame_jpeg(q["work"], q["name"], float(q["t"]), int(q.get("w", 960)), q.get("src", ""))
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=300")
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path.startswith("/shortmedia/"):
                work, file = unquote(u.path[len("/shortmedia/"):]).split("/", 1)
                return self.send_file(shortsapp.wd_of(work) / "shorts" / Path(file).name, ranged=True)
            if u.path.startswith("/media/"):
                work, file = unquote(u.path[len("/media/"):]).split("/", 1)
                p = work_dir(work) / Path(file).name
                return self.send_file(p, ranged=True)
            return self.send_error(404)
        except (ValueError, KeyError, FileNotFoundError) as e:
            return self.send_json({"error": str(e)}, 400)
        except (ConnectionError, BrokenPipeError):
            return

    def _route_post(self):
        u = urlparse(self.path)
        try:
            b = self.body_json()
            check_names(b)
            if u.path == "/api/v2/settings":
                import appsetup
                appsetup.save(b.get("folders") or {})
                restart = bool(b.get("restart")) and bool(os.environ.get("WOOTS_SUPERVISED")) and not _busy()
                if restart:                                       # every module read its paths at import: the supervisor starts a fresh copy
                    threading.Timer(1.0, lambda: os._exit(appsetup.RESTART)).start()
                return self.send_json({**appsetup.view(), "restarting": restart, "needs_restart": not restart})
            if u.path == "/api/v2/claude-models":
                return self.send_json(claudemodels.save(b.get("choices") or {}))
            if u.path == "/api/v2/engines":
                import engines
                if b["op"] == "choose":
                    engines.choose(b["job"], b["id"])
                elif b["op"] == "download":
                    engines.download(b["id"])
                else:
                    raise ValueError("unknown operation")
                return self.send_json(engines.view())
            if u.path == "/api/v2/channel":
                channel.save(b.get("fields") or {})
                return self.send_json({**channel.view(), "needs_restart": True})
            if u.path == "/api/v2/claude/login":
                import appsetup
                return self.send_json(appsetup.start_login())
            if u.path == "/api/v2/update-check":
                import appsetup
                return self.send_json(appsetup.check_update())
            if u.path == "/api/v2/computer/graphics":
                import appsetup
                return self.send_json(appsetup.get_graphics_tool())
            if u.path == "/api/v2/lesson":                          # the host adds the lesson Claude offered after a note to their own editing rules
                work, name = views.split_key(b["key"])
                v = next((x for x in reviewnotes.versions(work, name, b["stage"]) if x["n"] == int(b["n"])), None)
                if not v or not v.get("lesson"):
                    raise ValueError("there is no lesson to add")
                with _lock:
                    added = skillrules.add_lesson(v["lesson"])
                    reviewnotes.mark_lesson_added(work, name, b["stage"], v["n"])
                return self.send_json({"added": added})
            if u.path == "/api/v2/notes":
                work, name = views.split_key(b["key"])
                with _lock:
                    op = b["op"]
                    if op == "add":
                        reviewnotes.add(work, name, b["stage"], b.get("text"), b.get("t", 0), b.get("t_end"))
                    elif op == "edit":
                        reviewnotes.edit(work, name, b["stage"], int(b["id"]), b.get("text"))
                    elif op == "delete":
                        reviewnotes.delete(work, name, b["stage"], int(b["id"]))
                    else:
                        raise ValueError("unknown operation")
                return self.send_json(views.review(work, name, b["stage"]))
            if u.path == "/api/v2/clipchoice":
                import cutview
                work, name = views.split_key(b["key"])
                kind, t = b["kind"], float(b.get("t", 0))
                text = {"keep": "", "remove": "Take this clip out", "replace": "Use another take for this clip",
                        "trim": "Trim this clip"}.get(kind, "")
                with _lock:
                    cutview.set_choice(work, name, b["clip"], kind, text, t,
                                       {k: b[k] for k in ("span", "cut_start", "cut_end") if k in b})
                return self.send_json(views.review(work, name, "cut"))
            if u.path == "/api/v2/teaching":
                work, name = views.split_key(b["key"])
                with _lock:
                    teaching.set_status(work, name, b["id"], b["status"])
                return self.send_json(views.review(work, name, "cut"))
            if u.path == "/api/v2/footage/folder":
                work, name = views.split_key(b["key"])
                f = Path(os.path.abspath(b["folder"]))
                if not f.is_dir():
                    raise ValueError("that folder was not found")
                with _lock:
                    cfg = read_json(footage_file(work, name), {}) or {}
                    cfg["folder"] = str(f)
                    write_json(footage_file(work, name), cfg)
                return self.send_json(views.footage_view(work, name))
            if u.path == "/api/v2/footage/ignore":
                work, name = views.split_key(b["key"])
                rel = str(b["rel"])
                with _lock:
                    cfg = read_json(footage_file(work, name), {}) or {}
                    ign, inc = [x for x in cfg.get("ignore", []) if x != rel], [x for x in cfg.get("include", []) if x != rel]
                    if b.get("ignore"):
                        ign.append(rel)
                    elif footage_cfg.is_ignored(footage_cfg.with_titles(cfg, work, name), rel):
                        inc.append(rel)                          # it was left out by name (the finished video): The creator says it is material after all
                    cfg["ignore"], cfg["include"] = sorted(ign), sorted(inc)
                    write_json(footage_file(work, name), cfg)
                return self.send_json(views.footage_view(work, name))
            if u.path == "/api/v2/footage/choose":
                work, name = views.split_key(b["key"])
                with _lock:
                    shotmatch.choose(work, name, b["shot"], b.get("index"))
                    shotmatch.apply_to_beats(work, name)
                return self.send_json(views.footage_view(work, name))
            if u.path == "/api/v2/locks":
                import locks
                work, name = views.split_key(b["key"])
                data = clipmap.read_json(beatmap.path_of(work, name), None)
                if not data:
                    raise ValueError("there is no cut yet")
                with _lock:
                    if b["op"] == "lock":
                        locks.add(work, name, data, b.get("ids") or [], b.get("note", ""))
                    elif b["op"] == "unlock":
                        locks.unlock(work, name, int(b["id"]), b.get("ids"), data)
                    else:
                        raise ValueError("unknown operation")
                return self.send_json(views.lock_view(work, name))
            if u.path == "/api/v2/tags":
                import tags
                work, name = views.split_key(b["key"])
                with _lock:
                    op = b["op"]
                    if op == "add":
                        tags.add(work, name, b["rel"], b["start"], b["end"], b.get("label"), b.get("note", ""), views.clip_length(work, name, b["rel"]))
                    elif op == "edit":
                        tags.update(work, name, int(b["id"]), **{k: b[k] for k in ("start", "end", "label", "note") if k in b})
                    elif op == "delete":
                        tags.delete(work, name, int(b["id"]))
                    else:
                        raise ValueError("unknown operation")
                return self.send_json({"tags": tags.load(work, name)})
            if u.path == "/api/v2/footage/cut":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_rough_cut(work, name)["id"]})
            if u.path == "/api/v2/outline/edit":
                work, name = views.split_key(b["key"])
                with _lock:
                    outline.apply_op(work, name, b["op"], b)
                return self.send_json(views.outline_view(work, name))
            if u.path == "/api/v2/outline/write":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_outline(work, name, b.get("note", ""))["id"]})
            if u.path == "/api/v2/final/render":
                work, name = views.split_key(b["key"])
                with _lock:
                    job = start_final(work, name)
                return self.send_json({"id": job["id"]})
            if u.path == "/api/v2/final/score":
                work, name = views.split_key(b["key"])
                with _lock:
                    job = start_score(work, name)
                return self.send_json({"id": job["id"]})
            if u.path == "/api/v2/final/reveal":
                import shootplan
                work, name = views.split_key(b["key"])
                folder, _ = shootplan.footage_folder(work, name)
                d = folder or work_dir(work)
                platformx.open_folder(d)
                return self.send_json({"ok": True})
            if u.path == "/api/v2/publish/write":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_publish(work, name, b.get("note", ""))["id"]})
            if u.path == "/api/v2/publish/title":
                work, name = views.split_key(b["key"])
                with _lock:
                    publish.set_title(work, name, b.get("title", ""))
                return self.send_json(views.final(work, name))
            if u.path == "/api/v2/publish/field":
                work, name = views.split_key(b["key"])
                with _lock:
                    publish.set_field(work, name, b["field"], b.get("value"))
                return self.send_json(views.final(work, name))
            if u.path == "/api/v2/thumb/make":
                import thumbdraft
                work, name = views.split_key(b["key"])
                st = finalrender.state(work, name)
                if not st["finals"]:
                    raise ValueError("render the final first")
                text = " ".join(str(b.get("text", "")).split())
                with _lock:
                    thumbdraft.make(work_dir(work) / st["finals"][0]["file"], float(b.get("t", 0)), text, work_dir(work) / "final" / "thumbnail-draft.jpg")
                    publish.set_field(work, name, "thumb", {"t": b.get("t", 0), "text": text})
                return self.send_json(views.final(work, name))
            if u.path == "/api/v2/archive/run":
                import shootplan
                work, name = views.split_key(b["key"])
                if b.get("confirm") is not True:
                    raise ValueError("archiving deletes files for good: confirm first")
                folder, _ = shootplan.footage_folder(work, name)
                title = publish.load(work, name)["title"]
                if not title or not folder:
                    raise ValueError("choose the title and the footage folder first")
                return self.send_json({"id": start_archive(work, name, title, folder)["id"]})
            if u.path == "/api/v2/vision":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_vision(work, name)["id"]})
            if u.path == "/api/v2/options/find":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_find_options(work, name, b["clip"])["id"]})
            if u.path == "/api/v2/teaching/find":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_find_teaching(work, name)["id"]})
            if u.path == "/api/v2/make":
                work, name = views.split_key(b["key"])
                return self.send_json({"id": start_make_version(work, name, b["stage"])["id"]})
            if u.path == "/api/v2/job/stop":
                job = _jobs.get(b.get("id"))
                if job and not job["done"]:
                    job["stop"] = True
                return self.send_json({"ok": True})
            if u.path.startswith("/api/v2/shorts/"):
                return self.send_json(shorts_v2_post(u.path.rsplit("/", 1)[1], b))
            if u.path == "/api/v2/video/new":
                with _lock:
                    r = workflow.create(b.get("title", ""))
                return self.send_json({"key": views.key_of(r["work"], r["name"])})
            if u.path == "/api/dash/plan/refresh":              # one tiny Claude call (no tools) that reports the plan's limits; not under the global lock
                usage.refresh_plan()
                return self.send_json(usage.week_summary())
            if u.path == "/api/history/restore":
                with _lock:
                    return self.send_json(projectstore.restore(work_dir(b["work"]), b["id"]))
            if u.path == "/api/dash/assign":
                with _lock:
                    usage.assign(b["session"], b.get("target", ""))
                return self.send_json(usage.week_summary())
            if u.path.startswith("/api/resolve/"):
                op = u.path.rsplit("/", 1)[1]
                if op == "export":                               # reads the stitched video's files and writes only into <work>\resolve\: no global lock (probing ~80 files takes a while)
                    work_dir(b["work"])
                    try:
                        resolve_export.export(b["work"], b["name"])
                    except (OSError, RuntimeError) as e:
                        raise ValueError(f"the export failed: {e}")
                    return self.send_json(resolve_export.state(b["work"], b["name"]))
                if op == "reveal":                               # open the folder in Explorer
                    d = work_dir(b["work"]) / "resolve"
                    d.mkdir(exist_ok=True)
                    platformx.open_folder(d)
                    return self.send_json({"ok": True})
                return self.send_error(404)
            if u.path.startswith("/api/music/"):
                op = u.path.rsplit("/", 1)[1]
                if op == "audition":
                    return self.send_json(musicaudition.audition(b["work"], b["name"], int(b["bed"]), b["track"]))
                if op == "use":
                    with _lock:
                        return self.send_json(musicaudition.use(b["work"], b["name"], int(b["bed"]), b["track"]))
                return self.send_error(404)
            if u.path.startswith("/api/accuracy/"):
                op = u.path.rsplit("/", 1)[1]
                if op == "run":
                    return self.send_json(accuracy.start(b["work"], b["name"]))
                if op == "dismiss":
                    return self.send_json(accuracy.dismiss(b["work"], b["name"], b["id"], bool(b.get("undo"))))
                return self.send_error(404)
            return self.send_error(404)
        except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
            return self.send_json({"error": str(e)}, 400)

    def send_file(self, p: Path, ranged=False):
        if not p.is_file():
            return self.send_error(404)
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix in (".js", ".css", ".html"):
            ctype += "; charset=utf-8"
        start, end = 0, size - 1
        rng = self.headers.get("Range") if ranged else None
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:                                   # suffix range: last N bytes
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache" if not ranged else "max-age=60")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionError, BrokenPipeError):
                pass                                # the browser cancels ranges all the time while seeking

    def do_HEAD(self):
        self.do_GET()


HOST = "127.0.0.1"                                   # this computer only: nothing on the network can reach the app


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser on this PC")
    ap.add_argument("--sync", type=Path, metavar="INDEX_HTML",
                    help="write a graphic's markup text and clip durations from its CONFIG, then exit")
    args = ap.parse_args()
    if args.sync:
        html = args.sync.read_text(encoding="utf-8")
        cfg = read_config(html)
        if cfg is None:
            sys.exit("no CONFIG block (// CONFIG:BEGIN ... const CONFIG = {...}; // CONFIG:END)")
        args.sync.write_text(write_config(html, cfg), encoding="utf-8")
        print(f"synced {args.sync}")
        return
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("text/javascript", ".js")
    WORK.mkdir(parents=True, exist_ok=True)          # Settings only creates the workspace folder itself
    builder.recover()                                # runs that were alive when the app closed are not alive now
    srv = ThreadingHTTPServer((HOST, args.port), Handler)
    srv.daemon_threads = True
    url = f"http://localhost:{args.port}/"
    print(f"Woot's review app\n  open:     {url}\n  data:     {WORK}\n  Ctrl+C to stop.", flush=True)
    if not FFPROBE:
        print("  warning: ffprobe not found; assuming 30 fps")
    if args.open:
        import webbrowser
        webbrowser.open(url + "v2")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
